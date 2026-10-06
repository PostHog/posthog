"""What the destinations configured as one webhook URL share: generic webhook, Teams and Discord.

The URL is the credential, because whoever holds it can post into the channel. So it never
reaches an error message, a log line or a metric label, and the thread store keys on a digest
of it. That is also why these sends do not go through `posthog/egress`: an egress scope built
from the URL becomes a metric label.

None of these providers returns a handle to reply to, so a send returns None and a resolve
posts as a new message.
"""

import json
import hashlib
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Final

import requests

from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import AlertDestinationData

# Both fit inside the deliver activity's 10-second start_to_close, so a stalled destination fails
# this attempt instead of outliving it. A send still in flight when Temporal starts the next
# attempt posts a second copy, because no webhook provider takes an idempotency key.
CONNECT_TIMEOUT_SECONDS: Final = 3.0
READ_TIMEOUT_SECONDS: Final = 5.0


class WebhookUrlTransport(ABC):
    provider: str
    display_name: str
    headers: ClassVar[dict[str, str]] = {}

    def channel_target(self, target: AlertDestinationData) -> str:
        # A digest rather than the URL: the thread row would otherwise store the credential, and
        # some Teams URLs are longer than the column. A changed URL gives a new digest, so a
        # repointed destination starts a new thread.
        return hashlib.sha256(target.get("webhook_url", "").encode()).hexdigest()

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
        try:
            # `pinned_session` validates the URL and connects to the IPs it validated, which
            # closes the window where DNS changes between the check and the connection.
            with pinned_session(url) as session:
                request = session.prepare_request(
                    requests.Request(
                        "POST",
                        url,
                        # UTF-8 rather than `json=`, which escapes every non-ASCII character to six
                        # bytes or more. A provider limits the bytes it receives, so a body sized by
                        # its UTF-8 length must be sent as UTF-8.
                        data=json.dumps(body, ensure_ascii=False).encode(),
                        headers={"Content-Type": "application/json", **self.headers},
                    )
                )
                settings = session.merge_environment_settings(request.url, {}, True, None, None)
                # The adapter rather than `session.send`, and `stream=True` with no read. Even with
                # redirects off, the session reads a redirect's whole body to work out where it
                # points, so a destination answering 3xx with an unbounded body would fill the
                # worker's memory. The adapter returns the response unread and follows nothing.
                response = session.get_adapter(request.url or url).send(
                    request,
                    stream=True,
                    timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                    # Typed as optional, but it falls back to the session's own setting, which is True.
                    verify=True if settings["verify"] is None else settings["verify"],
                    cert=settings["cert"],
                    proxies=settings["proxies"],
                )
                status = response.status_code
                response.close()
        except SSRFBlockedError:
            raise DeliveryError(
                f"The {self.display_name} destination URL points to an address PostHog does not send to."
            ) from None
        except requests.RequestException as error:
            # Only the class name, and `from None` to keep the original out of the failure chain:
            # the text of a `requests` error carries the whole URL.
            raise DeliveryError(
                f"The {self.display_name} destination could not be reached: {type(error).__name__}"
            ) from None
        if not 200 <= status < 300:
            raise DeliveryError(f"The {self.display_name} destination refused the message with status {status}.")
