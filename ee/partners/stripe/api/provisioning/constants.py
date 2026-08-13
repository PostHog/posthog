"""Constants for the Stripe Projects provisioning namespace."""

from __future__ import annotations

import re

from posthog.models.integration import StripeIntegration

SUPPORTED_VERSIONS = ["0.1d"]
MAX_TIMESTAMP_DRIFT_SECONDS = 300

AUTH_CODE_TTL_SECONDS = 300
DEEP_LINK_TTL_SECONDS = 600
DEEP_LINK_MAX_PATH_LENGTH = 2000

# Control chars, whitespace, and backslashes never appear in a legitimate in-app path; they are the
# building blocks of header-injection and backslash-host open-redirect tricks, so reject them outright.
DEEP_LINK_DISALLOWED_PATH_CHARS = re.compile(r"[\x00-\x20\x7f-\x9f\\]")

ACCESS_TOKEN_EXPIRY_SECONDS = 365 * 24 * 3600

# Default scopes for a Stripe-issued token when the auth code requested none.
# This namespace enforces no scope ceiling; a code that names scopes gets those.
STRIPE_CONTRACTED_SCOPES: list[str] = StripeIntegration.SCOPES.split()

# Mirrors PersonalAPIKey.label's CharField(max_length=40) - keep in sync if that ever changes.
PROVISIONED_PAT_LABEL_MAX_LENGTH = 40

# Cap partner-supplied prefix below the full label length so " - {team_name}" still
# survives the truncation. A 37-char prefix would otherwise consume the whole label
# and the team name would disappear from the truncated result.
PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH = 25

# ---------------------------------------------------------------------------
# Service catalog vocabulary (spec-visible service ids)
# ---------------------------------------------------------------------------

ANALYTICS_SERVICE_ID = "analytics"
FREE_PLAN_SERVICE_ID = "free"
PAY_AS_YOU_GO_SERVICE_ID = "pay_as_you_go"
VALID_SERVICE_IDS: set[str] = {FREE_PLAN_SERVICE_ID, PAY_AS_YOU_GO_SERVICE_ID, ANALYTICS_SERVICE_ID}

ALL_CATEGORIES: list[str] = ["analytics", "feature_flags", "ai", "observability"]

# The built catalog is cached instance-wide under Stripe-specific keys, so
# billing is hit at most once per TTL and this namespace does not share catalog
# entries with the other provisioning surfaces.
SERVICES_CACHE_KEY = "stripe_provisioning:services"
SERVICES_CACHE_TTL = 3600
SERVICES_CACHE_RETRY_TTL = 300
SERVICES_CACHE_EXPIRES_KEY = "stripe_provisioning:services:expires_at"
SERVICES_CACHE_STORE_TTL = 86400

# ---------------------------------------------------------------------------
# Rate limiting - fixed-window counters keyed within this namespace on a fixed
# Stripe identity. Limits come from RATE_LIMIT_DEFAULTS; a value <= 0 disables
# the limit for that endpoint.
# ---------------------------------------------------------------------------

RATE_LIMIT_CACHE_PREFIX = "stripe_provisioning_rate:"
RATE_LIMIT_WINDOW_SECONDS = 3600
RATE_LIMIT_DEFAULTS: dict[str, int] = {
    "account_requests": 10,
    "token_exchanges": 20,
    "resource_creates": 20,
}
RATE_LIMIT_EVENT_NAMES: dict[str, str] = {
    "account_requests": "account_request",
    "token_exchanges": "token_exchange",
    "resource_creates": "resource_created",
}
