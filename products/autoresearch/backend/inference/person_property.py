"""
Remove a pipeline's output person property from every person who holds it.

Live scoring writes the champion's score to ``output_person_property`` only while the
pipeline's ``write_person_property`` is on. When someone turns it off, or archives or deletes a
pipeline that had it on, ``remove_output_person_property()`` sends ``$unset`` for the property
to each person who still has it. ``AutoresearchPropertyCleanupWorkflow`` in
``../temporal/workflows.py`` runs it.

The cleanup is safe to repeat: ``$unset`` of a missing property does nothing, and each page
reads the persons who still hold the property after the last person id it handled.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog

from posthog.schema import HogQLQuery

from posthog.api.capture import capture_batch_internal
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team
from posthog.models.user import User

from products.autoresearch.backend.inference.scoring import _resolve_distinct_ids
from products.autoresearch.backend.models import AutoresearchPipeline
from products.autoresearch.backend.query import BATCH_QUERY, QueryContext, run_hogql

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "autoresearch_property_cleanup"
CLEANUP_PAGE_SIZE = 1000

STOP_REENABLED = "reenabled"
STOP_PROPERTY_IN_USE = "property_in_use"


class PropertyCleanupError(Exception):
    """Raised when a page of ``$unset`` events is not fully accepted, so the activity retries."""


@frozen
class CleanupOutcome:
    persons_cleared: int
    # Why the cleanup ended before it reached every person, or None when it finished.
    stopped: str | None = None


def cleanup_stop_reason(*, team_id: int, pipeline_id: str, output_property: str) -> str | None:
    """
    Why the property must stay on persons now, or None.

    The pipeline writes it again when someone turned the setting back on. Another live pipeline
    can claim the name after an archive, and its scores must not be removed.
    """
    pipelines = AutoresearchPipeline.objects.for_team(team_id).exclude(status=AutoresearchPipeline.Status.ARCHIVED)
    if pipelines.filter(pk=pipeline_id, write_person_property=True).exists():
        return STOP_REENABLED
    if (
        pipelines.exclude(pk=pipeline_id)
        .filter(output_person_property=output_property, write_person_property=True)
        .exists()
    ):
        return STOP_PROPERTY_IN_USE
    return None


def remove_output_person_property(
    *,
    team: Team,
    pipeline_id: str,
    output_property: str,
    user: User | None,
    query_context: QueryContext = BATCH_QUERY,
    on_page: Callable[[int], None] | None = None,
) -> CleanupOutcome:
    """
    Send ``$unset`` for ``output_property`` to every person who has it, one page at a time.

    Before each page it checks ``cleanup_stop_reason()``, so a re-enable stops the cleanup within
    one page. ``on_page`` receives the running count after each page.
    """
    cleared = 0
    after: str | None = None
    while True:
        if stopped := cleanup_stop_reason(team_id=team.pk, pipeline_id=pipeline_id, output_property=output_property):
            logger.info("autoresearch_property_cleanup_stopped", pipeline_id=pipeline_id, reason=stopped)
            return CleanupOutcome(persons_cleared=cleared, stopped=stopped)
        person_ids = _persons_with_property(
            team=team, output_property=output_property, after=after, user=user, query_context=query_context
        )
        if not person_ids:
            return CleanupOutcome(persons_cleared=cleared)
        distinct_id_by_person = _resolve_distinct_ids(team=team, pipeline_id=pipeline_id, person_ids=person_ids)
        _send_unsets(
            team=team,
            pipeline_id=pipeline_id,
            output_property=output_property,
            distinct_ids=list(distinct_id_by_person.values()),
        )
        cleared += len(distinct_id_by_person)
        after = person_ids[-1]
        if on_page is not None:
            on_page(cleared)
        if len(person_ids) < CLEANUP_PAGE_SIZE:
            return CleanupOutcome(persons_cleared=cleared)


def _persons_with_property(
    *, team: Team, output_property: str, after: str | None, user: User | None, query_context: QueryContext
) -> list[str]:
    values: dict[str, Any] = {"property": output_property}
    after_clause = ""
    if after is not None:
        after_clause = "AND id > toUUID({after})"
        values["after"] = after
    tag_queries(product=Product.AUTORESEARCH, feature=Feature.QUERY)
    result = run_hogql(
        team=team,
        query=HogQLQuery(
            query=f"""
                SELECT id FROM persons
                WHERE JSONHas(properties, {{property}}) {after_clause}
                ORDER BY id
                LIMIT {CLEANUP_PAGE_SIZE}
            """,
            values=values,
        ),
        user=user,
        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        query_context=query_context,
    )
    return [str(row[0]) for row in result.rows]


def _send_unsets(*, team: Team, pipeline_id: str, output_property: str, distinct_ids: list[str]) -> None:
    if not distinct_ids:
        return
    timestamp = datetime.now(UTC)
    events = [
        {
            "event": "$set",
            "distinct_id": distinct_id,
            "timestamp": timestamp,
            "properties": {"$unset": [output_property], "$autoresearch_pipeline_id": pipeline_id},
            "options": {"process_person_profile": True},
        }
        for distinct_id in distinct_ids
    ]
    result = capture_batch_internal(
        events=events, token=team.api_token, event_source=EVENT_SOURCE, process_person_profile=True
    )
    # A warning means capture stored the event with person processing switched off, so the $unset never lands.
    if not result.succeeded() or result.warnings:
        raise PropertyCleanupError(
            f"Property cleanup events were not all accepted ({len(result.dropped)} dropped, "
            f"{len(result.retried)} exhausted retries, {len(result.unaccounted)} unaccounted, "
            f"{len(result.warnings)} stored with a warning)"
        )
