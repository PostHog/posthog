"""Slack events endpoint for SupportHog app."""

from posthog.ingress.slack.provider import build_slack_provider
from posthog.ingress.views import build_webhook_view

from products.conversations.backend.support_slack import get_support_slack_signing_secret

supporthog_event_handler = build_webhook_view(build_slack_provider(secret_getter=get_support_slack_signing_secret))
