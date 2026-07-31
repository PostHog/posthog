from dataclasses import dataclass
from typing import Any


@dataclass
class WhatsAppAppMentionWorkflowInputs:
    """Inputs for the WhatsApp mention workflow.

    ``message`` is the raw WhatsApp message object from the webhook payload — the
    Cloud API has no history-read endpoint, so the message is the entire
    conversation context.
    """

    integration_id: int
    wa_id: str
    message: dict[str, Any]
    user_id: int
    message_wamid: str
