"""
Facade API for cohorts.

This is the module that other apps should import from. It accepts plain inputs and
returns contract DTOs or primitives, never ORM instances or QuerySets.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from django.db import connection

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.tasks.calculate_cohort import schedule_static_cohort_count_refresh

from products.cohorts.backend.models.cohort import Cohort, ImportResolution


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


# The jsonb_path_exists patterns that find a reference to one action in a cohort's filters. The `id` and
# `id_str` variables both carry the action id, because a stored filter can hold it as a number or as a string.
_BEHAVIORAL_ACTION_JSONPATH = '$.** ? (@.event_type == "actions" && (@.key == $id || @.key == $id_str))'
_SEQUENCE_ACTION_JSONPATH = '$.** ? (@.seq_event_type == "actions" && (@.seq_event == $id || @.seq_event == $id_str))'


def cohorts_referencing_action(*, project_id: int, action_id: int, limit: int) -> list[CohortActionReference]:
    """Up to `limit` live cohorts of the project whose filters reference the action."""
    vars_json = json.dumps({"id": action_id, "id_str": str(action_id)})
    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    rows = (
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
