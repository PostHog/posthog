# In core ``posthog`` so the delivery paths (``ee/tasks``, ``products/exports``) and the
# ``products.slack_app`` handlers can share the bot's required scopes without crossing tach
# module boundaries.

from collections.abc import Iterable

import structlog

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

# Installs connected before the full set was requested (#57177) must reconnect before mentions work.
# channels:read/groups:read (member_joined_channel onboarding) are deliberately excluded so older
# installs degrade gracefully — they skip the welcome message rather than tripping a missing-scopes warning.
# canvases:write/files:write are also excluded: they were approved only recently, so every install
# authorized before then lacks them and gating mentions on them would hard-block those workspaces
# until they reconnect. The artifact delivery path
# (products/tasks/backend/logic/services/living_artifacts.py) checks them at point of use instead.
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


# Optional in the Slack app manifest, so an install can decline it. Workspaces with a strict
# app-approval policy refuse an app that demands it, so nothing may treat it as required.
CHAT_WRITE_CUSTOMIZE_SCOPE = "chat:write.customize"


def can_customize_message_appearance(integration: Integration) -> bool:
    """Whether messages from this install may set a per-message username and icon.

    Fails open when the granted set is unknown, which is what installs recorded before scopes
    were stored look like. The post path drops the appearance fields and posts again when Slack
    refuses them, so an optimistic answer costs one rejected call and never loses a message.
    """
    try:
        granted = SlackIntegration(integration).granted_scopes()
    except Exception:
        logger.warning("slack_granted_scopes_read_failed", integration_id=integration.id, exc_info=True)
        return True
    return not granted or CHAT_WRITE_CUSTOMIZE_SCOPE in granted


def has_scopes(integration: Integration, required: Iterable[str]) -> bool:
    """Whether the install granted these bot scopes. Fails closed, so an install whose
    granted set can't be read never enables anything."""
    try:
        return not SlackIntegration(integration).missing_scopes(required)
    except Exception:
        logger.warning("slack_bot_scope_check_failed", integration_id=integration.id, exc_info=True)
        return False


def bot_is_ready(integration: Integration) -> bool:
    """True when the install has every scope the @PostHog bot needs to answer mentions."""
    return has_scopes(integration, REQUIRED_SLACK_SCOPES)
