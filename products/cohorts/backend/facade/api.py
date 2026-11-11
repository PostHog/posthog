"""
Facade API for cohorts.

This is the module that other apps should import from. It accepts plain inputs and
returns contract DTOs or primitives, never ORM instances or QuerySets.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from django.db import connection, router

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.tasks.calculate_cohort import insert_cohort_from_query, schedule_static_cohort_count_refresh

from products.cohorts.backend.models.cohort import Cohort, CohortType, ImportResolution


def cohort_exists_for_team(*, team_id: int, cohort_id: int) -> bool:
    """Whether the team owns that cohort.

    A soft-deleted cohort still counts, so a caller that holds a reference to one keeps it.
    """
    return Cohort.objects.filter(team_id=team_id, id=cohort_id).exists()


@frozen
class CohortRef:
    id: int
    team_id: int
    created_by_id: int | None
    is_static: bool
    deleted: bool


def get_cohort_ref(*, team_id: int, cohort_id: int) -> CohortRef | None:
    cohort = (
        Cohort.objects.filter(team_id=team_id, id=cohort_id)
        .only("id", "team_id", "created_by_id", "is_static", "deleted")
        .first()
    )
    if cohort is None:
        return None
    return CohortRef(
        id=cohort.id,
        team_id=cohort.team_id,
        created_by_id=cohort.created_by_id,
        is_static=cohort.is_static,
        deleted=cohort.deleted,
    )


def add_person_to_static_cohort(*, team_id: int, cohort_id: int, person_uuid: str) -> bool:
    """Add one person to a static cohort. Returns False when the team has no person with that UUID.

    A person who is already a member is not inserted again, but the check and the insert are separate
    statements, so the caller must serialize concurrent calls for the same cohort and person.
    """
    cohort = Cohort.objects.get(team_id=team_id, id=cohort_id)
    resolution = ImportResolution()
    # save_state=False skips the full recount after each insert. The scheduled refresh updates the count.
    cohort.insert_users_list_by_uuid([person_uuid], team_id=team_id, save_state=False, import_resolution=resolution)
    if not resolution.matched_inputs:
        return False
    schedule_static_cohort_count_refresh(team_id=team_id, cohort_id=cohort_id)
    return True


@frozen
class CohortActionReference:
    """A live cohort whose filters reference an action, in a behavioral or a sequence condition."""

    id: int
    name: str | None
    created_at: datetime | None
    created_by_id: int | None


# A stored filter can hold the action id as a number or a string, so the patterns match `id` and `id_str`.
_BEHAVIORAL_ACTION_JSONPATH = '$.** ? (@.event_type == "actions" && (@.key == $id || @.key == $id_str))'
_SEQUENCE_ACTION_JSONPATH = '$.** ? (@.seq_event_type == "actions" && (@.seq_event == $id || @.seq_event == $id_str))'


def cohorts_referencing_action(*, project_id: int, action_id: int, limit: int) -> list[CohortActionReference]:
    """Up to `limit` live cohorts of the project whose filters reference the action."""
    vars_json = json.dumps({"id": action_id, "id_str": str(action_id)})
    rows = (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Cohort.objects.filter(team__project_id=project_id, deleted=False)
        .extra(
            where=[
                f"""
                jsonb_path_exists(filters, '{_BEHAVIORAL_ACTION_JSONPATH}', %s::jsonb)
                OR jsonb_path_exists(filters, '{_SEQUENCE_ACTION_JSONPATH}', %s::jsonb)
                """
            ],
            params=[vars_json] * 2,
        )
        .values("id", "name", "created_at", "created_by_id")
    )
    return [CohortActionReference(**row) for row in rows[:limit]]


def count_cohorts_referencing_actions(*, project_id: int, action_ids: Sequence[int]) -> dict[int, int]:
    """For each action, how many live cohorts of the project reference it. An action without one is absent."""
    if not action_ids:
        return {}
    cohort_table = Cohort._meta.db_table
    team_table = Team._meta.db_table
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {cohort_table}
                WHERE team_id IN (SELECT id FROM {team_table} WHERE project_id = %s) AND NOT deleted
                AND (
                    jsonb_path_exists(filters, '{_BEHAVIORAL_ACTION_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
                    OR jsonb_path_exists(filters, '{_SEQUENCE_ACTION_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))
                )
            ) AS matched
            GROUP BY aid
            """,
            [list(action_ids), project_id],
        )
        return dict(cursor.fetchall())


StaticCohortResyncSkipReason = Literal["not_found", "not_static", "no_source_query"]

# One re-sync request covers at most this many cohorts, from the console form or the Django admin action.
MAX_STATIC_COHORT_RESYNCS = 100


@frozen
class StaticCohortResyncCandidate:
    """A cohort staff asked to re-sync from its source query. `skip_reason` is None when it will be re-synced."""

    cohort_id: int
    name: str | None
    team_id: int | None
    team_name: str | None
    count: int | None
    skip_reason: StaticCohortResyncSkipReason | None


@frozen
class StaticCohortResync:
    queued: tuple[StaticCohortResyncCandidate, ...]
    skipped: tuple[StaticCohortResyncCandidate, ...]


def _resync_skip_reason(cohort: Cohort) -> StaticCohortResyncSkipReason | None:
    if not cohort.is_static:
        return "not_static"
    if not cohort.query:
        return "no_source_query"
    return None


def get_static_cohort_resync_candidates(*, cohort_ids: list[int]) -> list[StaticCohortResyncCandidate]:
    """Looks up cohorts across all teams for a staff re-sync, in the order of `cohort_ids`, and says which it skips."""
    # Staff re-sync cohorts of any team from the admin console, which checks staff access before this runs.
    # nosemgrep: idor-lookup-without-team
    cohorts = Cohort.objects.filter(id__in=cohort_ids).select_related("team").in_bulk()
    candidates: list[StaticCohortResyncCandidate] = []
    for cohort_id in cohort_ids:
        cohort = cohorts.get(cohort_id)
        if cohort is None:
            candidates.append(
                StaticCohortResyncCandidate(
                    cohort_id=cohort_id, name=None, team_id=None, team_name=None, count=None, skip_reason="not_found"
                )
            )
            continue
        candidates.append(
            StaticCohortResyncCandidate(
                cohort_id=cohort.id,
                name=cohort.name,
                team_id=cohort.team_id,
                team_name=cohort.team.name,
                count=cohort.count,
                skip_reason=_resync_skip_reason(cohort),
            )
        )
    return candidates


def queue_static_cohort_resyncs(*, cohort_ids: list[int]) -> StaticCohortResync:
    """Queues a re-sync of each static cohort from its source query, which adds the people who match it now and keeps existing members.

    It reads the cohorts again rather than trusting an earlier preview, because a cohort can change in between.
    """
    candidates = get_static_cohort_resync_candidates(cohort_ids=cohort_ids)
    queued = tuple(candidate for candidate in candidates if candidate.skip_reason is None)
    for candidate in queued:
        insert_cohort_from_query.delay(candidate.cohort_id, candidate.team_id)
    return StaticCohortResync(
        queued=queued,
        skipped=tuple(candidate for candidate in candidates if candidate.skip_reason is not None),
    )


@frozen
class CreatedCohort:
    id: int
    name: str
    # Whether the cohort's filters let it update in real time, which workflow triggers need.
    is_realtime: bool


def realtime_cohorts_available(*, team_id: int) -> bool:
    """Whether the team's users can use realtime cohorts, in workflows and flags."""
    from products.cohorts.backend.realtime_teams import is_serving_team

    return is_serving_team(team_id)


def find_cohort_by_description_prefix(*, team_id: int, prefix: str) -> CreatedCohort | None:
    """The oldest cohort of the team that is not deleted and whose description starts with `prefix`."""
    # Reads the writer, so a cohort created a moment ago by another import is found despite replica lag.
    cohort = (
        Cohort.objects.using(router.db_for_write(Cohort))
        .filter(team_id=team_id, deleted=False, description__startswith=prefix)
        .only("id", "name", "cohort_type", "is_static")
        .order_by("id")
        .first()
    )
    if cohort is None:
        return None
    # A cohort switched to static keeps its realtime type, but it no longer updates.
    return CreatedCohort(
        id=cohort.id,
        name=cohort.name or "",
        is_realtime=cohort.cohort_type == CohortType.REALTIME and not cohort.is_static,
    )


def create_cohort_from_filters(
    *, team_id: int, user_id: int, was_impersonated: bool, name: str, description: str, filters: dict[str, Any]
) -> CreatedCohort:
    """Creates a dynamic cohort the way the cohort API does: checked filters, a queued calculation and an activity log entry.

    Raises `ValueError` when the filters are not valid cohort filters.
    """
    from posthog.api.cohort import validate_filters_and_compute_realtime_support
    from posthog.event_usage import report_user_action
    from posthog.models import Team, User
    from posthog.models.activity_logging.activity_log import Detail, log_activity

    team = Team.objects.get(id=team_id)
    user = User.objects.get(id=user_id)
    clean_filters, cohort_type, errors = validate_filters_and_compute_realtime_support(filters, team)
    if errors:
        raise ValueError("; ".join(errors))
    cohort = Cohort.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        filters=clean_filters,
        cohort_type=cohort_type,
        is_calculating=True,
        created_by=user,
    )
    cohort.enqueue_calculation(initiating_user=user)
    report_user_action(user, "cohort created", cohort.get_analytics_metadata(), team=team)
    log_activity(
        organization_id=team.organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=cohort.id,
        scope="Cohort",
        activity="created",
        detail=Detail(name=cohort.name),
    )
    return CreatedCohort(id=cohort.id, name=cohort.name or "", is_realtime=cohort.cohort_type == CohortType.REALTIME)
