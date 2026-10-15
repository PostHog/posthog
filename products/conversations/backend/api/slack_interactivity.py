"""Slack interactivity endpoint for the SupportHog app.

Receives button clicks from the "open a ticket?" nudge prompt posted in channels
outside the configured support channels (``slack_nudge_enabled``, on by default).
The events endpoint posts the prompt; this endpoint handles the click and creates
— or skips — the ticket.
"""

from posthog.ingress.slack.provider import build_slack_interactivity_provider
from posthog.ingress.views import build_webhook_view

from products.conversations.backend.support_slack import get_support_slack_signing_secret

supporthog_interactivity_handler = build_webhook_view(
    build_slack_interactivity_provider(secret_getter=get_support_slack_signing_secret)
)
