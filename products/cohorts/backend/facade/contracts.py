from posthog.dataclasses import frozen


@frozen
class CohortRef:
    id: int
    team_id: int
    created_by_id: int | None
    is_static: bool
    deleted: bool
