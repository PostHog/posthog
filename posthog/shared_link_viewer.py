"""Lives outside posthog.auth so the hogql layer can import it without a circular import."""

from django.contrib.auth.models import AnonymousUser


class SharedLinkViewer(AnonymousUser):
    """Anonymous viewer of a publicly shared dashboard/insight/notebook.

    Publishing a share link is an explicit act, so shared queries execute without warehouse
    access control (`bypasses_warehouse_access_control`). Everything else stays userless:
    RBAC-scoped system tables stay hidden and only default property rules apply. Constructable
    only from an enabled SharingConfiguration.
    """

    bypasses_warehouse_access_control: bool = True
    # Django's AnonymousUser has no email; query modifiers read user.email for internal-user tagging.
    email: str | None = None

    def __init__(self, sharing_configuration):
        if not sharing_configuration.enabled:
            raise ValueError("SharedLinkViewer requires an enabled sharing configuration")
        super().__init__()
        self.sharing_configuration = sharing_configuration
        self.current_team_id = sharing_configuration.team_id
        self.distinct_id = f"shared-viewer-{sharing_configuration.team_id}"

    def readable_system_table_access_scopes(self) -> set[str]:
        return set()
