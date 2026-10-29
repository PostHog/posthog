"""The contract between the platform and one provider.

A transport knows a provider's wire format and nothing about alerts beyond the message it is
handed. What to say is decided before this, and where to send is resolved before this, so a
transport that gains a provider needs no change anywhere else.
"""

from typing import Any, Protocol, runtime_checkable

from posthog.dataclasses import frozen

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.facade.contracts import AlertDestinationData


@frozen
class MessageHandle:
    """Where a provider put a message, so a later send can reply to it or edit it.

    `external_ref` is the provider's own handle, for example `{"channel": ..., "ts": ...}` for
    Slack. Only the transport that issued one reads it.

    `root_content` is what a transport that can edit its posts sent to open a conversation, so a
    later edit keeps it. It is set only on the handle of that opening message.
    """

    external_ref: dict[str, str]
    root_content: dict[str, Any] | None = None


class DeliveryError(Exception):
    """A send the provider refused. The caller decides whether to retry."""


class DeliveryTransport(Protocol):
    provider: str

    def channel_target(self, target: AlertDestinationData) -> str:
        """Which conversation this destination is, as the provider names it.

        A repointed destination gives a different answer, which is what stops a reply going
        into the thread the previous channel held.
        """
        ...

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        """Sends one message, and says where it landed.

        Returns None when the provider gives nothing back to reply to, which a webhook does.
        A transport that cannot thread ignores `in_reply_to`, so a caller never branches on the
        provider. That optional argument is the whole mechanism: a declared capability set would
        be a second statement of the same fact, free to disagree with it.
        """
        ...


@runtime_checkable
class RootEditor(Protocol):
    """A transport that can update the message that opened a conversation.

    The opening content stays as it was posted, because it is the only record of what fired that
    the thread does not repeat. Only the current-state line changes.
    """

    def edit_root(self, *, team_id: int, target: AlertDestinationData, root: MessageHandle, state_line: str) -> None:
        """Rewrites the opening message with `state_line` under its original content."""
        ...
