from posthog.dataclasses import frozen


@frozen
class AuthorizationDashboard:
    id: int
    created_by_id: int | None
    restricted: bool
    collaborator_user_ids: tuple[int, ...]
