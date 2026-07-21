"""
Contract types for conversations.

Stable, framework-free shapes other products may import. No Django imports.
"""

from pydantic.dataclasses import dataclass


class SupportSlackNotConfigured(Exception):
    """The team has no SupportHog bot token configured."""


class SupportSlackChannelsUnavailable(Exception):
    """The bot's channel list could not be resolved (Slack error or too many pages)."""


class SupportMessageSendError(Exception):
    """Slack rejected a SupportHog bot message.

    ``code`` is the Slack error code (e.g. ``not_in_channel``); ``retry_after`` carries
    the requested wait in seconds when Slack rate-limited the post, else None.
    """

    def __init__(self, code: str, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True)
class SupportChannel:
    """A Slack channel visible to the SupportHog bot."""

    id: str
    name: str
    is_member: bool
