# In core ``posthog`` so the delivery paths (``ee/tasks``, ``products/exports``) and the
# ``products.slack_app`` handlers can share the bot's required scopes without crossing tach
# module boundaries.

import structlog

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

# Installs connected before the full set was requested (#57177) must reconnect before mentions work.
# channels:read/groups:read (member_joined_channel onboarding) are deliberately excluded so older
# installs degrade gracefully — they skip the welcome message rather than tripping a missing-scopes warning.
# canvases:write/files:write are also excluded: they are still in Slack review
# (SlackIntegrationScopeInReview), so OAuth never grants them on US/EU Cloud — gating mentions on
# them would hard-block every prod install. The artifact delivery path checks them at point of use
# instead (products/tasks/backend/logic/services/living_artifacts.py).
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


def bot_is_ready(integration: Integration) -> bool:
    """True when the install has every scope the @PostHog bot needs to answer mentions."""
    try:
        return not SlackIntegration(integration).missing_scopes(REQUIRED_SLACK_SCOPES)
    except Exception:
        logger.warning("slack_bot_scope_check_failed", integration_id=integration.id, exc_info=True)
        return False
