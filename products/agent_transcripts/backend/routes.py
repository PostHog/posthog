from posthog.api.routing import RouterRegistry

from products.agent_transcripts.backend.presentation.views import AgentTranscriptViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.organizations.register(
        r"agent_transcripts",
        AgentTranscriptViewSet,
        "organization_agent_transcripts",
        ["organization_id"],
    )
