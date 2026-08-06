"""Lives outside posthog.auth to avoid a circular import when imported by posthog.hogql."""

from typing import Optional


class SyntheticUser:
    """Tagged base class for non-real principals authenticated via service tokens.

    Behavior (subclasses may override `readable_system_table_access_scopes`):
      * `Database.create_for` hides RBAC-scoped system tables the principal's
        scopes don't cover (`readable_system_table_access_scopes`); the base hides all.
      * `has_perm` / `has_module_perms` always return False; Django
        permission checks against a SyntheticUser silently deny.
      * `id` is None; do not use it as a foreign key. Use `current_team_id`.
    """

    email: Optional[str] = None
    is_staff: bool = False
    is_superuser: bool = False
    is_active: bool = True
    is_anonymous: bool = False

    def __init__(self, team, distinct_id: str):
        self.team = team
        self.current_team_id = team.id
        self.is_authenticated = True
        self.pk = -1
        self.id: Optional[int] = None
        self.distinct_id = distinct_id
        self.groups: list = []
        self.user_permissions: list = []

    def has_perm(self, perm, obj=None):
        return False

    def has_module_perms(self, app_label):
        return False

    def readable_system_table_access_scopes(self) -> set[str]:
        """Resource scopes whose access-controlled system tables this principal may read (empty = none)."""
        return set()
