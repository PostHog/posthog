from typing import Final

# Destination templates that send a message and are therefore created as workflows. Mirrors
# MESSAGING_DESTINATION_TEMPLATE_IDS in
# products/workflows/frontend/Workflows/fromDestination/messagingDestinationTemplates.ts. Keep both in sync.
MESSAGING_DESTINATION_TEMPLATE_IDS: Final[frozenset[str]] = frozenset(
    {
        "template-slack",
        "template-discord",
        "template-microsoft-teams",
        "template-whatsapp",
        "template-mailgun-send-email",
        "template-kudosity-sms",
    }
)

# Shared with FEATURE_FLAGS.WORKFLOWS_MESSAGING_DESTINATIONS in frontend/src/lib/constants.tsx.
MESSAGING_DESTINATIONS_FLAG_KEY: Final[str] = "workflows-messaging-destinations"


def messaging_destination_guidance(template_id: str) -> str:
    """The error an agent reads when it tries to create a messaging destination over MCP."""
    return (
        f"Template '{template_id}' sends messages, so it is created as a workflow rather than a destination. "
        "Call workflows-create with an actions array of an event trigger (id 'trigger_node', config "
        "{type: 'event', filters: {events: [...]}}), a 'function' action whose config.template_id is "
        f"'{template_id}' with the same config.inputs, and an exit (id 'exit_node'), connected by two "
        "'continue' edges. Read the template's inputs with cdp-function-templates-retrieve and follow the "
        "building-workflows skill."
    )
