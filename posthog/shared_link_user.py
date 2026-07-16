"""Lives outside posthog.auth so the hogql layer can import it without a circular import."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.models import AnonymousUser

if TYPE_CHECKING:
    from posthog.models.sharing_configuration import SharingConfiguration


class SharedLinkUser(AnonymousUser):
    """Anonymous viewer of a publicly shared dashboard/insight/notebook"""

    # Django's AnonymousUser has no email; query modifiers read user.email for internal-user tagging.
    email: str | None = None

    def __init__(self, sharing_configuration: SharingConfiguration):
        if not sharing_configuration.enabled:
            raise ValueError("SharedLinkUser requires an enabled sharing configuration")
        super().__init__()
        self.sharing_configuration = sharing_configuration
        # Read by query analytics tagging (QueryRunner.run) and modifier resolution.
        self.distinct_id = f"shared-viewer-{sharing_configuration.team_id}"

    def readable_system_table_access_scopes(self) -> set[str]:
        """No RBAC identity - no access-controlled system tables (read by Database.create_for)."""
        return set()
