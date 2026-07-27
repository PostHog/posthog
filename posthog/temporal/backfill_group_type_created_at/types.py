from dataclasses import dataclass
from typing import TypedDict

from pydantic import BaseModel


class GroupTypeUpdate(TypedDict):
    """A single created_at correction, produced by the plan activity and applied by the apply activity."""

    group_type: str
    group_type_index: int
    current_created_at: str  # ISO-8601
    new_created_at: str  # ISO-8601


class BackfillGroupTypeCreatedAtInput(BaseModel):
    """Input for the group type created_at backfill workflow.

    Imports stamp posthog_grouptypemapping.created_at with wall-clock now, which
    postdates the imported events. HogQL then masks $group_N for events older than
    created_at, hiding historical group data. This workflow recomputes created_at
    from the earliest event actually carrying each group, across every environment
    (team) in the project.
    """

    team_id: int
    dry_run: bool = False


@dataclass
class PlanBackfillInput:
    """Input for planning the backfill — resolves the project and reads both stores."""

    team_id: int


@dataclass
class ApplyBackfillInput:
    """Input for applying the planned created_at updates to Postgres.

    `updates` is the list produced by the planning activity, each item carrying
    `group_type_index` and the `new_created_at` ISO string to write.
    """

    project_id: int
    updates: list[GroupTypeUpdate]


class BackfillGroupTypeCreatedAtError(Exception):
    """Fatal error during the backfill.

    Listed in the plan activity's RetryPolicy.non_retryable_error_types (by class name),
    so Temporal fails fast instead of retrying an error that won't resolve on its own.
    """

    pass
