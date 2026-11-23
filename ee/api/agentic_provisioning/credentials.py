"""Provisioned credentials: partner-labeled personal API keys."""

from __future__ import annotations

import unicodedata

from django.db import transaction
from django.db.models import Q

from posthog.accessible_teams import AccessibleTeams
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.personal_api_key_minting import mint_personal_api_key
from posthog.scopes.ceilings import narrow_scopes_to_ceiling

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


def delete_provisioned_pats(app: OAuthApplication, *, team_id: int, user: User | None = None) -> int:
    """Delete the personal API keys ``app`` minted for ``team_id``, for one user or for all of them.

    Keys ``app`` minted that no longer carry any project restriction count as minted for
    every project.

    Deletes key by key so the activity log records each deletion. Keys the user created
    themselves carry no ``provisioned_by``, so they are never matched.
    """
    # A key whose owner removed its project restriction still reaches the project, so it goes too.
    keys = PersonalAPIKey.objects.filter(provisioned_by=app).filter(
        Q(scoped_teams__contains=[team_id]) | Q(scoped_teams=[]) | Q(scoped_teams__isnull=True)
    )
    if user is not None:
        keys = keys.filter(user=user)

    deleted = 0
    for key in keys:
        key.delete()
        deleted += 1

    return deleted


def maybe_create_provisioned_pat(
    user: User,
    team: Team,
    app: OAuthApplication | None,
    granted_scope: str | None,
    label_prefix: str | None = None,
    *,
    access_token: OAuthAccessToken | None = None,
    replace_existing: bool = False,
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

    ``access_token`` is the bearer token of the request. The mint locks its row and mints
    nothing when the row is gone, so a mint that races a session revocation cannot leave a
    working key behind. Both revoke functions in ``posthog/models/oauth.py`` delete the
    token rows before the keys, so the two sides take their row locks in the same order.

    ``replace_existing`` first deletes the keys ``app`` minted earlier for this user and
    team, in the same transaction as the mint. It deletes them even when no new key is
    minted, so a rotation always ends the earlier keys.
    """
    if not app:
        return None

    with transaction.atomic():
        if access_token is not None and not _lock_live_access_token(access_token):
            return None

        if replace_existing:
            delete_provisioned_pats(app, team_id=team.id, user=user)

        pat_scopes = _provisioned_pat_scopes(team, app, granted_scope)
        if not pat_scopes:
            return None

        return _mint_provisioned_pat(user, team, app, pat_scopes, label_prefix)


def _lock_live_access_token(access_token: OAuthAccessToken) -> bool:
    locked = OAuthAccessToken.objects.select_for_update().filter(pk=access_token.pk).values_list("pk", flat=True)
    return locked.first() is not None


def _provisioned_pat_scopes(team: Team, app: OAuthApplication, granted_scope: str | None) -> list[str] | None:
    if not app.provisioning.issues_personal_api_key:
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

    return pat_scopes


def _mint_provisioned_pat(
    user: User, team: Team, app: OAuthApplication, pat_scopes: list[str], label_prefix: str | None
) -> str | None:
    try:
        label_base = f"{label_prefix} - {team.name}" if label_prefix else team.name
        # PersonalAPIKey.label is stored as a CharField(max_length=40); cap the
        # final string to match so we never violate the column constraint.
        label = label_base[:PROVISIONED_PAT_LABEL_MAX_LENGTH]

        # A savepoint, so a failed insert does not abort the caller's transaction.
        with transaction.atomic():
            minted = mint_personal_api_key(
                user,
                label=label,
                scopes=pat_scopes,
                teams=AccessibleTeams.for_user(user, [team.id]),
                organization_ids=[str(team.organization_id)],
                provisioned_by=app,
            )

        return minted.value
    except Exception:
        capture_exception(additional_properties={"user_id": user.id, "team_id": team.id})
        return None
