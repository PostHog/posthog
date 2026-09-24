"""The contract between the platform and one provider.

A transport knows a provider's wire format and nothing about alerts beyond the message it is
handed. What to say is decided before this, and where to send is resolved before this, so a
transport that gains a provider needs no change anywhere else.
"""

from typing import Protocol

from posthog.dataclasses import frozen

from products.alerts.backend.delivery.message import AlertMessage
from products.alerts.backend.facade.contracts import AlertDestinationData

REPLY = "reply"
UPDATE = "update"


@frozen
class MessageHandle:
    """Where a provider put a message, so a later send can reply to it or edit it.

    `external_ref` is the provider's own handle, for example `{"channel": ..., "ts": ...}` for
    Slack. Only the transport that issued one reads it.
    """

    external_ref: dict[str, str]


class DeliveryError(Exception):
    """A send the provider refused. The caller decides whether to retry."""


class DeliveryTransport(Protocol):
    capabilities: frozenset[str]
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
        `in_reply_to` is ignored by a transport that does not declare `REPLY`, so a caller
        never branches on the provider.
        """
        ...
