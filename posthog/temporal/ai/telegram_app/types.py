from dataclasses import dataclass
from typing import Any


@dataclass
class TelegramAppMentionWorkflowInputs:
    """Inputs for the Telegram mention workflow.

    ``message`` is the raw Telegram message object from the webhook update — the Bot
    API has no history-read endpoint, so the message (plus its embedded
    ``reply_to_message``) is the entire conversation context.
    """

    integration_id: int
    chat_id: str
    message: dict[str, Any]
    user_id: int
    update_id: int
