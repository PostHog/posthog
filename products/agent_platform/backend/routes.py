from posthog.api.routing import RouterRegistry

from products.agent_platform.backend.presentation.views import (
    AgentApplicationViewSet,
    AgentFleetViewSet,
    AgentMemoryViewSet,
    AgentNativeToolsViewSet,
    AgentRevisionViewSet,
)

# Skill / custom-tool template registry is disabled pending a rethink.
# from products.agent_platform.backend.registry_api import AgentCustomToolTemplateViewSet, AgentSkillTemplateViewSet


def register_routes(routers: RouterRegistry) -> None:
    agent_applications = routers.projects.register(
        r"agent_applications",
        AgentApplicationViewSet,
        "project_agent_applications",
        ["project_id"],
    )
    agent_applications.register(
        r"revisions",
        AgentRevisionViewSet,
        "project_agent_application_revisions",
        ["project_id", "application_id"],
    )
    agent_applications.register(
        r"memory",
        AgentMemoryViewSet,
        "project_agent_application_memory",
        ["project_id", "application_id"],
    )
    routers.projects.register(
        r"agent_native_tools",
        AgentNativeToolsViewSet,
        "project_agent_native_tools",
        ["project_id"],
    )
    # Skill / custom-tool template routes disabled pending a registry rethink.
    # routers.projects.register(
    #     r"agent_skill_templates", AgentSkillTemplateViewSet,
    #     "project_agent_skill_templates", ["project_id"],
    # )
    # routers.projects.register(
    #     r"agent_custom_tool_templates", AgentCustomToolTemplateViewSet,
    #     "project_agent_custom_tool_templates", ["project_id"],
    # )
    routers.projects.register(
        r"agent_fleet",
        AgentFleetViewSet,
        "project_agent_fleet",
        ["project_id"],
    )
