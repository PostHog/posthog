"""Conversations' consumers on the customer-facing GitHub App, the SupportHog Slack and Teams bots and the Mailgun email routes.

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


def _run_email_inbound(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_mailgun_inbound_message  # noqa: PLC0415

    accept_mailgun_inbound_message(delivery)


def _email_inbound_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    from products.conversations.backend.facade.api import mailgun_inbound_delivery_ownership  # noqa: PLC0415

    return mailgun_inbound_delivery_ownership(delivery)


def _run_email_outbound(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_mailgun_outbound_message  # noqa: PLC0415

    accept_mailgun_outbound_message(delivery)


def _email_outbound_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    from products.conversations.backend.facade.api import mailgun_outbound_delivery_ownership  # noqa: PLC0415

    return mailgun_outbound_delivery_ownership(delivery)


def _run_email_capture(delivery: WebhookDelivery) -> None:
    from products.conversations.backend.facade.api import accept_mailgun_captured_message  # noqa: PLC0415

    accept_mailgun_captured_message(delivery)


def _email_capture_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    from products.conversations.backend.facade.api import mailgun_capture_delivery_ownership  # noqa: PLC0415

    return mailgun_capture_delivery_ownership(delivery)


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
    WebhookConsumer(
        name="conversations_email_inbound",
        provider="mailgun",
        app="inbound",
        event_types=frozenset({"message_received"}),
        handler=_run_email_inbound,
        ownership=_email_inbound_ownership,
    ),
    WebhookConsumer(
        name="conversations_email_outbound",
        provider="mailgun",
        app="outbound",
        event_types=frozenset({"message_sent"}),
        handler=_run_email_outbound,
        ownership=_email_outbound_ownership,
    ),
    WebhookConsumer(
        name="conversations_email_capture",
        provider="mailgun",
        app="capture",
        event_types=frozenset({"message_received"}),
        handler=_run_email_capture,
        ownership=_email_capture_ownership,
    ),
)
