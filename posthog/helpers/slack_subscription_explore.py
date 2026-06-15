"""Shared helpers for the subscription "Dive into the data" button.

Lives in core ``posthog`` (not under ``products/slack_app``) on purpose: the button is built by
the subscription delivery paths in ``ee/tasks`` and ``products/exports`` and handled by the Slack
app in ``products/slack_app`` — and module boundaries (tach) forbid those senders from importing
``products.slack_app``. Core is the one place all three may depend on. Kept dependency-light
(Django signing + the Integration model only) so it never drags the heavy bot pipeline onto the
subscription send path.
"""

from typing import Any

from django.core import signing

import structlog
import posthoganalytics

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

# Scopes the conversational bot exercises end-to-end. Slack stores the granted scope set
# per install, so tenants who connected the Slack integration before the full scope set was
# requested in prod (2026-05-04, #57177) must reconnect before mentions can work.
#
# ``member_joined_channel`` (channel-onboarding) additionally needs ``channels:read`` and
# ``groups:read``. Those are in the Slack app manifest but **not** in the required set on
# purpose: workspaces that connected before they were added keep working — they just skip
# the welcome message instead of seeing a "missing scopes" warning.
#
# ``api.py`` re-exports this as ``POSTHOG_CODE_REQUIRED_SLACK_SCOPES`` for backwards compatibility.
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

# action_id on the interactive button + callback_id on the modal it opens.
EXPLORE_ACTION_ID = "subscription_explore_in_thread"
EXPLORE_VIEW_CALLBACK_ID = "subscription_explore_submit"
EXPLORE_PROMPT_BLOCK_ID = "subscription_explore_prompt"
EXPLORE_PROMPT_ACTION_ID = "prompt"

EXPLORE_TOKEN_SALT = "posthog_code_subscription_explore"
# Subscription messages linger in a channel — allow a generous window to click through.
EXPLORE_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7

# Docs page explaining how to invite/enable the @PostHog bot in a channel.
BOT_SETUP_DOCS_URL = "https://posthog.com/docs/slack-app"

# Org-level rollout gate for the whole explore button (both the interactive and the
# docs-link variants). Configure in PostHog as an organization group flag and ramp by
# org. Orgs without the flag see exactly the pre-feature message. Subscriptions whose
# org can't be resolved fail closed — same stance as the prompt-guide gate.
SUBSCRIPTION_EXPLORE_BUTTON_FEATURE_FLAG_KEY = "subscription-explore-button"


def explore_button_enabled(*, organization_id: str) -> bool:
    """True when the explore button is rolled out to this organization.

    Takes a primitive org id (not a Subscription) so this core helper stays free of any
    product-model dependency. The senders read the org off their subscription's team and,
    on the async delivery paths, call this inside ``database_sync_to_async`` — ``feature_enabled``
    issues a blocking decide request and must not run on the event loop.
    """
    if not organization_id:
        return False
    return bool(
        posthoganalytics.feature_enabled(
            SUBSCRIPTION_EXPLORE_BUTTON_FEATURE_FLAG_KEY,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
        )
    )


def bot_is_ready(integration: Integration) -> bool:
    """True when this Slack install has every scope the conversational bot needs."""
    try:
        return not SlackIntegration(integration).missing_scopes(REQUIRED_SLACK_SCOPES)
    except Exception:
        logger.warning("subscription_explore_scope_check_failed", integration_id=integration.id, exc_info=True)
        return False


def make_explore_token(*, integration_id: int, resource_name: str) -> str:
    """Sign the context needed to safely route a button click back to this install.

    Signed (not a random cache key) so the click survives across the long display window
    without us holding server state per delivered message. The handler still verifies the
    decoded ``integration_id`` belongs to the clicking Slack workspace before acting.
    """
    return signing.dumps(
        {"integration_id": integration_id, "resource_name": resource_name},
        salt=EXPLORE_TOKEN_SALT,
    )


def decode_explore_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        decoded = signing.loads(token, salt=EXPLORE_TOKEN_SALT, max_age=EXPLORE_TOKEN_MAX_AGE_SECONDS)
    except signing.SignatureExpired:
        # Token outlived the display window — same outcome as a bad signature, but called out
        # explicitly to match the existing _decode_picker_context idiom in api.py.
        return None
    except signing.BadSignature:
        return None
    return decoded if isinstance(decoded, dict) else None


def build_explore_button(
    integration: Integration | None, *, enabled: bool, resource_name: str, utm_tags: str
) -> dict[str, Any] | None:
    """A Slack ``actions`` element inviting the channel to ask @PostHog about this report in-thread.

    The conversational bot is GA, so rather than hide the entry point when it isn't set up we
    nudge the user to enable it:
    - Bot fully scoped -> an interactive button that opens the "Dive into the data" modal.
    - Slack connected but bot not invited / missing scopes -> a link button pointing at the docs.

    Returns ``None`` when the feature is disabled for this org (``enabled`` is False) or there's no
    Slack integration to attach to — the one place that decides whether and which button to show.
    Shared by both the insight/dashboard and AI subscription delivery paths so the button stays identical.
    """
    if not enabled or integration is None:
        return None
    if bot_is_ready(integration):
        return {
            "type": "button",
            "action_id": EXPLORE_ACTION_ID,
            "text": {"type": "plain_text", "text": "Dive into the data 🔍"},
            "value": make_explore_token(integration_id=integration.id, resource_name=resource_name),
        }
    # Pure link button (no action_id) — matches the existing link buttons and is acked by the
    # interactivity handler's catch-all 200.
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Ask PostHog about this 🔍"},
        "url": f"{BOT_SETUP_DOCS_URL}?{utm_tags}",
    }
