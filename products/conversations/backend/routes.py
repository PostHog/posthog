from posthog.api.routing import RouterRegistry

from products.conversations.backend.api import (
    TicketAlertRuleViewSet,
    TicketIncidentViewSet,
    TicketViewSet,
    TicketViewViewSet,
    ZendeskImportViewSet,
)


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"conversations/tickets",
        TicketViewSet,
        "environment_conversations_tickets",
        ["team_id"],
    )
    routers.projects.register(
        r"conversations/alert_rules",
        TicketAlertRuleViewSet,
        "project_conversations_alert_rules",
        ["team_id"],
    )
    routers.projects.register(
        r"conversations/incidents",
        TicketIncidentViewSet,
        "project_conversations_incidents",
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
