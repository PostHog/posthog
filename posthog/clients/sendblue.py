from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)

SENDBLUE_API_BASE_URL = "https://api.sendblue.co/api"


class SendBlueError(Exception):
    pass


class SendBlueNotConfigured(SendBlueError):
    pass


class SendBlueClient:
    """
    Thin wrapper around the SendBlue REST API. Used as the underlying provider for
    the SMS personal integration.
    """

    def __init__(self) -> None:
        if not settings.SENDBLUE_API_KEY or not settings.SENDBLUE_API_SECRET:
            raise SendBlueNotConfigured("SendBlue is not configured for this instance")
        self._headers = {
            "sb-api-key-id": settings.SENDBLUE_API_KEY,
            "sb-api-secret-key": settings.SENDBLUE_API_SECRET,
            "Content-Type": "application/json",
        }
        self._from_number = settings.SENDBLUE_FROM_NUMBER or None

    def send_message(self, to: str, body: str) -> dict:
        payload: dict[str, str] = {"number": to, "content": body}
        if self._from_number:
            payload["from_number"] = self._from_number
        try:
            response = requests.post(
                f"{SENDBLUE_API_BASE_URL}/send-message",
                json=payload,
                headers=self._headers,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.exception("sendblue.send_message_failed", to=to, error=str(exc))
            raise SendBlueError(f"SendBlue send-message failed: {exc}") from exc
        return response.json()


def get_sendblue_client() -> SendBlueClient:
    return SendBlueClient()


def is_sendblue_configured() -> bool:
    return bool(settings.SENDBLUE_API_KEY and settings.SENDBLUE_API_SECRET and settings.SENDBLUE_FROM_NUMBER)
