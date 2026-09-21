"""Conversations' consumers on the customer-facing GitHub App and the SupportHog Slack and Teams bots.

The registry imports this module on the first delivery, so it stays cheap: every callable defers
its own product import.
"""

from posthog.ingress.contracts import DeliveryOwnership, WebhookConsumer, WebhookDelivery
from posthog.ingress.slack.provider import SLACK_EVENT_TYPES, SLACK_INTERACTIVITY_APP, SLACK_INTERACTIVITY_TYPES
from posthog.ingress.teams.provider import TEAMS_ACTIVITY_TYPES


def _run_conversations(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_github_event  # noqa: PLC0415

    accept_github_event(delivery)


def _run_slack_events(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_slack_event  # noqa: PLC0415

    accept_slack_event(delivery)


def _run_slack_interactivity(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_slack_interactivity  # noqa: PLC0415

    accept_slack_interactivity(delivery)


def _slack_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    from products.conversations.backend.facade.api import slack_delivery_ownership  # noqa: PLC0415

    return slack_delivery_ownership(delivery)


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
        name="conversations_slack",
        provider="slack",
        app="supporthog",
        event_types=SLACK_EVENT_TYPES,
        handler=_run_slack_events,
        # The unique inbound receipt row is the idempotency here, so a redelivery must reach it.
        dedup=False,
        ownership=_slack_ownership,
    ),
    WebhookConsumer(
        name="conversations_slack_interactivity",
        provider="slack",
        app=SLACK_INTERACTIVITY_APP,
        event_types=SLACK_INTERACTIVITY_TYPES,
        handler=_run_slack_interactivity,
        # The same workspace lookup as the events consumer: an interactive payload names the
        # workspace too, so a click on a workspace the other region holds is forwarded there.
        ownership=_slack_ownership,
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
