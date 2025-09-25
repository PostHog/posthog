from products.messaging.backend.max_tools import CreateMessageTemplateTool

from ee.hogai.ai.product_base import AIProduct


class MessagingAIProduct(AIProduct):
    name = "messaging"
    routing_prompt = "Use when creating message templates or working with messaging."
    # TODO: Populate concise JTBD/workflow system_prompt when product enable/disable is active
    system_prompt = ""
    tools = [
        CreateMessageTemplateTool,
    ]
