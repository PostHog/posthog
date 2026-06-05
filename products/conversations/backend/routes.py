from posthog.api.routing import RouterRegistry

from products.conversations.backend.api import TicketViewSet, TicketViewViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"conversations/tickets",
        TicketViewSet,
        "environment_conversations_tickets",
        ["team_id"],
    )
    # Dual-route surface preserved for existing clients (project + environment).
    routers.register_legacy_dual_route(
        r"conversations/views",
        TicketViewViewSet,
        "project_conversations_views",
        ["team_id"],
    )
