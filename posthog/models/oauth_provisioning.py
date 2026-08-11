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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Records who set the account-request rate limit, so a verification flip doesn't overwrite an
# explicit admin override. Empty for rows that pre-date the field.
RateLimitSource = Literal["", "default_unverified", "default_verified", "admin"]


class ProvisioningRateLimits(BaseModel):
    """Per-endpoint hourly overrides. None means "use the endpoint's default"."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    account_requests: int | None = None
    token_exchanges: int | None = None
    resource_creates: int | None = None
    github_grants: int | None = None
    wizard_runs: int | None = None


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

    rate_limits: ProvisioningRateLimits = Field(default_factory=ProvisioningRateLimits)
    rate_limit_source: RateLimitSource = ""
