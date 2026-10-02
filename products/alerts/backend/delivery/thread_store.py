"""Where a provider conversation is remembered between sends.

A resolve replies to the message that fired rather than posting beside it, which needs the
handle from that first send. The store is an interface before it is a table: the key shape
follows the delivery table in the implementation RFC, which is not settled, and the null
implementation lets a transport ship without waiting on it.

The key carries the firing as well, which the RFC's own shape does not. Without it the table
holds one row per alert instead of one per firing, and there is no version of that decision
under which a second firing should reply into the first firing's thread.

It carries no `notification_key`. That field only ever differs from the group once fan-in
ships, and fan-in was deprioritized on 2026-09-28, so the group is what identifies a
conversation until then.
"""

from datetime import datetime
from typing import Protocol

from posthog.dataclasses import frozen

from products.alerts.backend.delivery.transport import MessageHandle


@frozen
class ThreadKey:
    """Which conversation a message belongs to.

    Two parts carry that. `grouping_key` separates one group's conversation from another's, and
    `episode_started_at` separates one firing from the next. Without the episode a key names the
    alert rather than the firing, so every resolve an alert ever sends replies into the thread
    its first firing opened. Without the group, two groups of one configuration share a thread.

    One object rather than five arguments, because four of the parts are strings and a caller
    that passes them separately can reorder them without a typecheck noticing.
    """

    configuration_id: str
    grouping_key: str
    provider: str
    channel_target: str
    episode_started_at: datetime


class ThreadStore(Protocol):
    def handle_for(self, key: ThreadKey) -> MessageHandle | None: ...

    def remember(self, key: ThreadKey, handle: MessageHandle) -> None: ...


class NullThreadStore:
    """Remembers nothing, so every message is a new one.

    Not a regression: the platform sends nothing today, so there is no thread to continue. It
    does mean a resolve posts beside the message that fired rather than under it.
    """

    def handle_for(self, key: ThreadKey) -> MessageHandle | None:
        return None

    def remember(self, key: ThreadKey, handle: MessageHandle) -> None:
        return None
