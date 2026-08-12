"""Provisioned credentials: partner-labeled personal API keys."""

from __future__ import annotations

import unicodedata

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, mask_key_value
from posthog.scopes import narrow_scopes_to_ceiling

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    PROVISIONED_PAT_LABEL_MAX_LENGTH,
    PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError


def validate_label_prefix(raw: object) -> str | None:
    """Validate the optional ``label_prefix`` request field.

    Returns ``None`` when the field is absent or empty (caller creates an
    unprefixed label). Raises an ``invalid_label_prefix``
    :class:`ProvisioningError` when the field is present but malformed (wrong
    type, too long, or contains control or format characters that would render
    badly in the user's PAT list).
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProvisioningError("invalid_label_prefix", "label_prefix must be a string")

    stripped = raw.strip()
    if not stripped:
        return None

    if len(stripped) > PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH:
        raise ProvisioningError(
            "invalid_label_prefix",
            f"label_prefix must be {PROVISIONED_PAT_LABEL_PREFIX_MAX_LENGTH} characters or fewer",
        )

    # Reject Unicode control (Cc), format (Cf), and line/paragraph separators (Zl/Zp).
    # Cf is the important one - it includes bidi overrides (U+202A-U+202E) and
    # isolates (U+2066-U+2069), which a partner could use to re-order surrounding
    # text in the user's settings page (Trojan Source class). Cc covers C0 + DEL.
    if any(unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"} for c in stripped):
        raise ProvisioningError("invalid_label_prefix", "label_prefix must not contain control or format characters")

    return stripped


def maybe_create_provisioned_pat(
    user: User, team: Team, app: OAuthApplication | None, granted_scope: str | None, label_prefix: str | None = None
) -> str | None:
    """Create a Personal API Key for a provisioned user and return the raw key value.

    Gated by ``app.provisioning.issues_personal_api_key``: off by default, so most
    apps never receive a provisioned PAT (the OAuth token is the credential).
    Returns ``None`` when the gate is off, and the caller omits ``personal_api_key``
    from the response entirely.

    When enabled (the grandfathered legacy Stripe app), the key carries the granted
    OAuth token's scopes (``granted_scope``) narrowed to the app's current ceiling,
    so a provisioned PAT can exceed neither what the user granted nor what the app
    may hold. Minting from the ceiling alone would hand out optional scopes the
    grant never included. A flag-on app with an unseeded ceiling mints nothing: an
    empty-scope PAT fails every scope check, and widening to a wildcard would
    bypass the ceiling.

    scoped_teams is set to [team.id] so the PAT only grants access to the team
    being provisioned, matching the scoping of the OAuth token issued in the
    same flow. Without this, a provisioning call from an existing user would
    return a PAT that reaches across every team the user already belongs to.

    ``label_prefix`` should be pre-validated by ``validate_label_prefix``; pass
    ``None`` (or any falsy value) to label the key with just the team name.
    """
    if not app or not app.provisioning.issues_personal_api_key:
        return None
    if not app.ceiling_scopes:
        capture_provisioning_event("pat_mint", "skipped_unseeded_ceiling", partner=app, team_id=team.id)
        return None

    granted = (granted_scope or "").split()
    if "*" in granted:
        # A legacy wildcard token covers everything, so the ceiling is the cap.
        pat_scopes = app.ceiling_scopes
    else:
        pat_scopes = narrow_scopes_to_ceiling([s for s in granted if ":" in s], app.ceiling_scopes) or []

    if not pat_scopes:
        capture_provisioning_event("pat_mint", "skipped_no_granted_scopes", partner=app, team_id=team.id)
        return None

    try:
        api_key_value = generate_random_token_personal()
        label_base = f"{label_prefix} - {team.name}" if label_prefix else team.name
        # PersonalAPIKey.label is stored as a CharField(max_length=40); cap the
        # final string to match so we never violate the column constraint.
        label = label_base[:PROVISIONED_PAT_LABEL_MAX_LENGTH]

        PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=hash_key_value(api_key_value),
            mask_value=mask_key_value(api_key_value),
            scopes=pat_scopes,
            scoped_teams=[team.id],
            scoped_organizations=[str(team.organization_id)],
        )

        return api_key_value
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "team_id": team.id})
        return None
