"""Conversations' consumers on the customer-facing GitHub App and the SupportHog Teams bot.

The registry imports this module on the first delivery, so it stays cheap: every callable defers
its own product import.
"""

from posthog.ingress.contracts import DeliveryOwnership, WebhookConsumer, WebhookDelivery
from posthog.ingress.teams.provider import TEAMS_ACTIVITY_TYPES


def _run_conversations(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_github_event  # noqa: PLC0415

    accept_github_event(delivery)


def _run_teams_events(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_teams_event  # noqa: PLC0415

    accept_teams_event(delivery)


def _teams_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    from products.conversations.backend.facade.api import teams_delivery_ownership  # noqa: PLC0415

    return teams_delivery_ownership(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="conversations",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment"}),
        handler=_run_conversations,
    ),
    WebhookConsumer(
        name="conversations_teams",
        provider="teams",
        app="supporthog",
        event_types=TEAMS_ACTIVITY_TYPES,
        handler=_run_teams_events,
        ownership=_teams_ownership,
    ),
)
