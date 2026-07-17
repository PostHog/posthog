from django.conf import settings

from posthog.api.routing import RouterRegistry

from products.conversations.backend.api import (
    CrossRegionOrgVerificationViewSet,
    TicketViewSet,
    TicketViewViewSet,
    ZendeskImportViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    # HMAC-authenticated receiver for the sibling region's enrichment run. Both
    # Cloud regions need it; single-region deployments have no sibling to answer.
    if settings.CLOUD_DEPLOYMENT in ("US", "EU") or settings.DEBUG or settings.TEST:
        routers.root.register(
            r"conversations/internal/verify_org_memberships",
            CrossRegionOrgVerificationViewSet,
            "conversations_verify_org_memberships",
        )

    routers.projects.register(
        r"conversations/tickets",
        TicketViewSet,
        "environment_conversations_tickets",
        ["team_id"],
    )
    routers.projects.register(
        r"conversations/zendesk_imports",
        ZendeskImportViewSet,
        "project_conversations_zendesk_imports",
        ["team_id"],
    )
    # Dual-route surface preserved for existing clients (project + environment).
    routers.register_legacy_dual_route(
        r"conversations/views",
        TicketViewViewSet,
        "project_conversations_views",
        ["team_id"],
    )
