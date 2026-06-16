# In core ``posthog`` so the delivery paths (``ee/tasks``, ``products/exports``) can import these
# without crossing tach's ``products.slack_app`` boundary.

from typing import Any

import structlog

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

# Installs connected before the full set was requested (#57177) must reconnect before mentions work.
# channels:read/groups:read (member_joined_channel onboarding) are deliberately excluded so older
# installs degrade gracefully — they skip the welcome message rather than tripping a missing-scopes warning.
REQUIRED_SLACK_SCOPES: frozenset[str] = frozenset(
    {
        "app_mentions:read",
        "users:read",
        "users:read.email",
        "chat:write",
        "channels:history",
        "groups:history",
        "reactions:write",
    }
)

BOT_SETUP_DOCS_URL = "https://posthog.com/docs/slack-app"


def bot_is_ready(integration: Integration) -> bool:
    try:
        return not SlackIntegration(integration).missing_scopes(REQUIRED_SLACK_SCOPES)
    except Exception:
        logger.warning("subscription_explore_scope_check_failed", integration_id=integration.id, exc_info=True)
        return False


def build_explore_hint(integration: Integration | None, *, utm_tags: str) -> dict[str, Any] | None:
    """Slack context block nudging the channel to @PostHog this report (or to set the bot up)."""
    if integration is None:
        return None
    if bot_is_ready(integration):
        text = "💬 Reply in this thread and mention *@PostHog* with a question to dig into this report."
    else:
        text = f"💬 <{BOT_SETUP_DOCS_URL}?{utm_tags}|Set up the @PostHog bot> to ask follow-up questions about your reports here."
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}
