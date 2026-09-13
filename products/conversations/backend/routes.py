from posthog.api.routing import RouterRegistry

from products.conversations.backend.api import (
    TicketPatternViewSet,
    TicketTopicOverrideViewSet,
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
    routers.projects.register(
        r"conversations/patterns",
        TicketPatternViewSet,
        "project_conversations_patterns",
        ["team_id"],
    )
    routers.projects.register(
        r"conversations/pattern_overrides",
        TicketTopicOverrideViewSet,
        "project_conversations_pattern_overrides",
        ["team_id"],
    )
