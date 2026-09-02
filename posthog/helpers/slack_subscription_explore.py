# In core ``posthog`` so the delivery paths (``ee/tasks``, ``products/exports``) can import this
# without crossing tach's ``products.slack_app`` boundary.

from typing import Any

from posthog.helpers.slack_scopes import bot_is_ready
from posthog.models.integration import Integration

BOT_SETUP_DOCS_URL = "https://posthog.com/docs/slack-app"


def build_explore_hint_text(integration: Integration | None, *, utm_tags: str, ai_enabled: bool) -> str | None:
    """mrkdwn nudging the channel to @PostHog this report (or to set the bot up).

    Returns ``None`` when there's no Slack install or the org hasn't approved AI data processing —
    we don't nudge people toward the AI bot when their org hasn't opted into AI. Plain-text variant
    used where Slack only accepts mrkdwn (e.g. a gallery upload's ``initial_comment``).
    """
    if integration is None or not ai_enabled:
        return None
    if bot_is_ready(integration):
        return "💬 Reply in this thread and mention *@PostHog* with a question to dig into this report."
    return f"💬 <{BOT_SETUP_DOCS_URL}?{utm_tags}|Set up the @PostHog bot> to ask follow-up questions about your reports here."


def build_explore_hint(integration: Integration | None, *, utm_tags: str, ai_enabled: bool) -> dict[str, Any] | None:
    """Slack context block nudging the channel to @PostHog this report (or to set the bot up).

    Returns ``None`` in the same cases as ``build_explore_hint_text``.
    """
    text = build_explore_hint_text(integration, utm_tags=utm_tags, ai_enabled=ai_enabled)
    if text is None:
        return None
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}
