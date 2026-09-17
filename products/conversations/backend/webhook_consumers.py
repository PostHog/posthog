"""Conversations' consumer on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: the callable defers
its own product import.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_conversations(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_github_event  # noqa: PLC0415

    accept_github_event(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="conversations",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment"}),
        handler=_run_conversations,
    ),
)
