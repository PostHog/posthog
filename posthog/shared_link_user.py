"""Lives outside posthog.auth so the hogql layer can import it without a circular import."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from django.contrib.auth.models import AnonymousUser

if TYPE_CHECKING:
    from posthog.models.sharing_configuration import SharingConfiguration
    from posthog.rbac.team_default_access import TeamDefaultAccess


class SharedLinkUser(AnonymousUser):
    """Anonymous viewer of a publicly shared dashboard/insight/notebook.

    Warehouse tables resolve against the team's *default* access rules (member/role grants
    don't bind an anonymous viewer) - see TeamDefaultAccess. System tables stay hidden.
    """

    # Django's AnonymousUser has no email; query modifiers read user.email for internal-user tagging.
    email: str | None = None

    def __init__(self, sharing_configuration: SharingConfiguration):
        if not sharing_configuration.enabled:
            raise ValueError("SharedLinkUser requires an enabled sharing configuration")
        super().__init__()
        self.sharing_configuration = sharing_configuration
        # Request-scoped memo: this instance is created once per request and flows to every
        # consumer (each tile's runner, each database build, the cache fingerprint), so the
        # team's default access rules load once per request - mirrors how the view's
        # user_access_control is reused across a dashboard's runners. Set lazily by
        # posthog.rbac.team_default_access.for_shared_link_user.
        self.team_default_access: Optional[TeamDefaultAccess] = None
        # Read by query analytics tagging (QueryRunner.run) and modifier resolution.
        self.distinct_id = f"shared-viewer-{sharing_configuration.team_id}"

    def readable_system_table_access_scopes(self) -> set[str]:
        """No RBAC identity - no access-controlled system tables (read by Database.create_for)."""
        return set()
