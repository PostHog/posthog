from posthog.api.routing import RouterRegistry

from products.conversations.backend.api import (
    AIContextAccountPropertiesViewSet,
    AIReplyPlaybookViewSet,
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
        r"conversations/ai_reply_playbook",
        AIReplyPlaybookViewSet,
        "project_conversations_ai_reply_playbook",
        ["team_id"],
    )
    routers.projects.register(
        r"conversations/ai_context_account_properties",
        AIContextAccountPropertiesViewSet,
        "project_conversations_ai_context_account_properties",
        ["team_id"],
    )
