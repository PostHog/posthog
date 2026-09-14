"""Conversations' consumer on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: the handler defers
its own product import.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_conversations(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.webhooks import dispatch_github_event  # noqa: PLC0415

    dispatch_github_event(delivery.event_type, dict(delivery.payload), delivery.delivery_id)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="conversations",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment"}),
        handler=_run_conversations,
    ),
)
