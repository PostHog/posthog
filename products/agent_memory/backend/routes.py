from posthog.api.routing import RouterRegistry

from products.agent_memory.backend.presentation.views import AgentMemoryViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"agent_memory", AgentMemoryViewSet, "project_agent_memory", ["team_id"])
