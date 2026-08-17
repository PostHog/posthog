from posthog.api.routing import RouterRegistry

from products.conversations.backend.api import (
    AgentAvailabilityViewSet,
    TicketViewSet,
    TicketViewViewSet,
    ZendeskImportViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"conversations/tickets",
        TicketViewSet,
        "project_conversations_tickets",
        ["team_id"],
    )
    routers.projects.register(
        r"conversations/zendesk_imports",
        ZendeskImportViewSet,
        "project_conversations_zendesk_imports",
        ["team_id"],
    )
    # Dual-route surface preserved for existing clients (project + environment).
    routers.projects.register(
        r"conversations/views",
        TicketViewViewSet,
        "project_conversations_views",
        ["team_id"],
    )
    # Organization-nested: assignees are validated against organization membership, so agent
    # availability applies across every project in the org.
    routers.organizations.register(
        r"conversations/availability",
        AgentAvailabilityViewSet,
        "organization_conversations_availability",
        ["organization_id"],
    )
