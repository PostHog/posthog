"""Where a provider conversation is remembered between sends.

A resolve replies to the message that fired rather than posting beside it, which needs the
handle from that first send. The store is an interface before it is a table: the key shape
follows the delivery table in the implementation RFC, which is not settled, and the null
implementation lets a transport ship without waiting on it.
"""

from typing import Protocol

from products.alerts.backend.delivery.transport import MessageHandle


class ThreadStore(Protocol):
    def handle_for(
        self, *, configuration_id: str, notification_key: str, provider: str, channel_target: str
    ) -> MessageHandle | None: ...

    def remember(
        self, *, configuration_id: str, notification_key: str, provider: str, channel_target: str, handle: MessageHandle
    ) -> None: ...


class NullThreadStore:
    """Remembers nothing, so every message is a new one.

    Not a regression: the platform sends nothing today, so there is no thread to continue. It
    does mean a resolve posts beside the message that fired rather than under it.
    """

    def handle_for(
        self, *, configuration_id: str, notification_key: str, provider: str, channel_target: str
    ) -> MessageHandle | None:
        return None

    def remember(
        self, *, configuration_id: str, notification_key: str, provider: str, channel_target: str, handle: MessageHandle
    ) -> None:
        return None
