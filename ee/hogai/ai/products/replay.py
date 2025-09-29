from products.replay.backend.max_tools import SearchSessionRecordingsTool

from ee.hogai.ai.products_infrastructure import AIProduct


class ReplayAIProduct(AIProduct):
    name = "replay"
    routing_prompt = "Use when the task involves session recordings filters/search."
    # TODO: Populate concise JTBD/workflow system_prompt when product enable/disable is active
    system_prompt = ""
    tools = [
        SearchSessionRecordingsTool,
    ]
