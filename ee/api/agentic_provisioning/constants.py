"""Shared constants for the agentic provisioning API."""

from __future__ import annotations

import re

AUTH_CODE_CACHE_PREFIX = "provisioning_auth_code:"
PENDING_AUTH_CACHE_PREFIX = "provisioning_pending_auth:"
GITHUB_GRANT_CACHE_PREFIX = "provisioning_github_grant:"
DEEP_LINK_CACHE_PREFIX = "provisioning_deep_link:"

AUTH_CODE_TTL_SECONDS = 300
PENDING_AUTH_TTL_SECONDS = 600
DEEP_LINK_TTL_SECONDS = 600
DEEP_LINK_MAX_PATH_LENGTH = 2000
# Control chars, whitespace, and backslashes never appear in a legitimate in-app path; they are the
# building blocks of header-injection and backslash-host open-redirect tricks, so reject them outright.
DEEP_LINK_DISALLOWED_PATH_CHARS = re.compile(r"[\x00-\x20\x7f-\x9f\\]")

CIMD_DOMAIN_RATE_LIMIT_PREFIX = "cimd_registration_domain_rate:"
CIMD_DOMAIN_RATE_LIMIT_MAX = 5
CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS = 3600

# The client registration endpoint dereferences a caller-supplied URL synchronously, so it is
# capped per client_id on top of the per-IP and per-domain CIMD limits. Generous enough for a
# partner iterating on a broken metadata document, low enough that it is not an amplifier.
CLIENT_REGISTRATION_RATE_LIMIT_PREFIX = "provisioning_client_registration:"
CLIENT_REGISTRATION_RATE_LIMIT_MAX = 30
CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS = 3600
# Ceiling across every client_id one address checks, so registering a pile of clients does not
# multiply the per-client budget into an unbounded number of synchronous outbound fetches.
# Well above the per-client limit, since one address legitimately operating several partners
# should still be able to spend a full budget on each.
CLIENT_REGISTRATION_IP_RATE_LIMIT_MAX = 120

# Per-partner endpoint budgets live in ee/api/agentic_provisioning/ratelimits.py,
# declared on each handler with @rate_limited.

# Per-user wizard-run budget matching the session endpoint's limits (2/hour, 5/day), which
# can't run here — the partner path has no session user on the request. Unlike the session
# endpoint's throttles, which count only non-failed/non-cancelled runs from the DB, this is a
# plain request counter: failed runs still consume partner quota. Aligning it with the
# outcome-aware counting is a pending follow-up.
WIZARD_RUN_USER_RATE_LIMIT_PREFIX = "provisioning_wizard_run_user:"
WIZARD_RUN_USER_RATE_LIMITS: list[tuple[str, int, int]] = [
    ("burst", 2, 3600),
    ("day", 5, 86400),
]

# Per-IP ceiling on cross-region forwarding. The region proxy decides to forward before
# DRF authenticates or throttles anything, and each forwarded request occupies a worker
# until the other region answers, so this is the only limit an unauthenticated caller
# meets on that path. Two orders of magnitude above the peak per-IP forwarding rate real
# partner traffic reaches, so it leaves room for bulk provisioning while still bounding
# how many workers one caller can tie up.
REGION_PROXY_RATE_LIMIT = "300/minute"

# Matches the state parameter allowed by the auth endpoint's RFC 7636 spec.
SAFE_STATE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,256}$")
CODE_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_\-]+")

# Mirrors PersonalAPIKey.label's CharField(max_length=40) - keep in sync if that ever changes.
PROVISIONED_PAT_LABEL_MAX_LENGTH = 40

# Cap partner-supplied prefix below the full label length so " - {team_name}" still
# survives the truncation. A 37-char prefix would otherwise consume the whole label
# and the team name would disappear from the truncated result.
PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH = 25

# Default access token expiry.
ACCESS_TOKEN_EXPIRY_SECONDS = 365 * 24 * 3600
PARTNER_TOKEN_EXPIRY_SECONDS = 3600
