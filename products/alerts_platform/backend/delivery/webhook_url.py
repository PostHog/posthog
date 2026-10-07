"""What the destinations configured as one webhook URL share: generic webhook, Teams and Discord.

The URL is the credential, because whoever holds it can post into the channel. So it never
reaches an error message, a log line or a metric label, and the thread store keys on a digest
of it. That is also why these sends do not go through `posthog/egress`: an egress scope built
from the URL becomes a metric label.

None of these providers returns a handle to reply to, so a send returns None and a resolve
posts as a new message.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.delivery.wire import credential_digest, post_json
from products.alerts_platform.backend.facade.contracts import AlertDestinationData


class WebhookUrlTransport(ABC):
    provider: str
    display_name: str
    headers: ClassVar[dict[str, str]] = {}

    def channel_target(self, target: AlertDestinationData) -> str:
        # Some Teams URLs are longer than the column, which a digest also avoids. A changed URL
        # gives a new digest, so a repointed destination starts a new thread.
        return credential_digest(target.get("webhook_url", ""))

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        url = target.get("webhook_url")
        if not url:
            raise DeliveryError(f"This {self.display_name} destination has no webhook URL.")
        self.check_url(url)
        self._post(self.send_url(url), self.body_for(message))
        return None

    def check_url(self, url: str) -> None:
        """Refuses a URL this provider never issues. The SSRF check runs on every send regardless."""
        return None

    def send_url(self, url: str) -> str:
        """The URL to post to, which a provider can extend with its own query parameters."""
        return url

    @abstractmethod
    def body_for(self, message: AlertMessage) -> dict[str, Any]: ...

    def _post(self, url: str, body: dict[str, Any]) -> None:
        post_json(url, body, display_name=self.display_name, headers=self.headers)
