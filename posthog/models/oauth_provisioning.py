"""Storage shape for ``OAuthApplication.provisioning_config``.

A provisioning partner's capabilities and quotas live in one JSONB column rather than
a column each. The column is internal storage, not a public DTO: nothing in the API surface
serializes it directly, so it is free to change shape here without a schema migration.

Every capability defaults to False. A partner is granted what it may do explicitly, so a key
that has never been written reads as "not allowed" rather than inheriting whatever default the
column happened to be created with. That is what makes adding a capability safe: existing rows
do not silently acquire it.

``extra="ignore"`` rather than ``forbid`` so a row written by a newer release still loads on an
older one mid-deploy. Unknown keys are rejected where an operator can act on the message
instead - see the admin form - because silently dropping a mistyped capability key would read
to an operator as a capability that was granted.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PartnerTier(StrEnum):
    """Where a partner sits on the two trust axes, derived from the app row on every read.

    Auth axis: a client that must prove itself (private_key_jwt against a published key
    set, or a client secret) sits in the JWKS rows; a PKCE-public client, whose client_id
    anyone can send, sits in the PUBLIC rows. Attested axis: the app presented a valid
    ``posthog_verification_token`` at CIMD registration, so abuse is traceable to a real
    PostHog organization.

    Derived, never stored: a partner moves tier the moment it publishes a key set or
    attests, with no admin involvement and no persisted value to go stale.
    """

    PUBLIC = "public"
    PUBLIC_ATTESTED = "public_attested"
    JWKS = "jwks"
    JWKS_ATTESTED = "jwks_attested"


# Admin override value that disables an endpoint's limit outright. Distinct from the
# BLOCKED tier multiplier (0) on purpose: an operator typing 0 into a form must not
# accidentally grant infinity, so 0 is rejected at the write paths.
UNLIMITED_OVERRIDE = -1


class ProvisioningConfig(BaseModel):
    """What a provisioning partner may do, and how often.

    Whether an app is a partner at all stays on ``OAuthApplication.is_provisioning_partner``:
    that is identity rather than capability, and it is the column admin and querysets filter on.

    Frozen, because ``OAuthApplication.provisioning`` parses the column afresh on every read:
    ``app.provisioning.active = True`` would otherwise mutate a throwaway object and persist
    nothing, which for a capability check fails open and looks like it worked. Change it with
    ``app.update_provisioning(active=True)`` instead.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    active: bool = False
    # Kill switch for a misbehaving partner. Checked separately from `active` so re-running the
    # self-serve defaults cannot turn a partner an admin switched off back on.
    disabled: bool = False

    can_create_accounts: bool = False
    can_provision_resources: bool = False
    # Exchanging GitHub OAuth codes and starting cloud wizard runs both act well beyond ordinary
    # provisioning, so neither follows from being a partner - each is granted on its own.
    can_use_github_grants: bool = False
    can_start_wizard_runs: bool = False

    # Only for partners trusted enough that the blast radius of the app being compromised is
    # understood: a deep link mints a full web session, and skipping consent links an existing
    # account without the user agreeing to it.
    can_issue_deep_links: bool = False
    skip_existing_user_consent: bool = False

    # Grandfathered: only the legacy Stripe app still mints a Personal API Key.
    issues_personal_api_key: bool = False

    # Per-endpoint hourly overrides, keyed by rate-limit endpoint name. An absent key
    # means the tier-derived budget applies; UNLIMITED_OVERRIDE disables the limit.
    # Every value stored here is admin-authored: the self-serve tiers are derived at
    # request time and never written, which is what made rate_limit_source obsolete.
    rate_limits: dict[str, int] = Field(default_factory=dict)

    @field_validator("rate_limits", mode="before")
    @classmethod
    def _normalize_rate_limits(cls, value: object) -> dict[str, int]:
        """Load blobs written by any release: the old fixed-field shape stored null
        for "no override" and 0 for "unlimited"."""
        if not isinstance(value, dict):
            return {}
        limits: dict[str, int] = {}
        for key, raw in value.items():
            try:
                parsed = int(raw)
            except (TypeError, ValueError):
                # Dropped like a null rather than raised: pydantic lets a TypeError out of a
                # validator, and the config is re-parsed on every read, so one unreadable
                # value would fail every request for that partner.
                continue
            limits[str(key)] = UNLIMITED_OVERRIDE if parsed <= 0 else parsed
        return limits
