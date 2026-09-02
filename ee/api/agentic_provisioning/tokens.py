"""Partner OAuth token scoping: which teams a provisioning token can reach.

A partner token carries its restriction in ``scoped_teams`` alone — the
standard OAuth permission check treats an empty ``scoped_teams`` as
unrestricted — so every mutation here is deliberate about never leaving a
token empty-scoped by accident.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl


def user_can_access_team(user: User, team: Team) -> bool:
    """Verify the user has at least member-level access to the team.

    Org membership alone does not prove access for advanced-permissions
    orgs that restrict individual teams. Without this check the agentic
    provisioning resolve flow could grant scoped access to a private team
    as long as the user had any team in the same org.
    """
    return UserAccessControl(user=user, team=team).check_access_level_for_object(team, required_level="member")


def lock_application(application_id: uuid.UUID) -> OAuthApplication | None:
    """Row-lock the OAuthApplication so direct-mint serializes with revoke_application_sessions.

    The revoke updates this row first and holds the lock for its whole transaction before
    sweeping tokens, so a mint that takes the same lock is forced into one of two safe orders:
    it holds the lock and its new tokens land before the revoke's sweep (which then catches
    them), or the revoke committed first and the caller reads the now-visible
    `sessions_revoked_at` and rejects. Must be called inside `transaction.atomic()`.
    """
    return OAuthApplication.objects.select_for_update().filter(pk=application_id).first()


def compute_partner_scoped_teams(
    application: OAuthApplication | None,
    user: User,
    base_team_id: int,
) -> list[int]:
    """Compute the durable scope for a partner OAuth token at issuance/refresh.

    Returns the set of every team where ``TeamProvisioningConfig.application ==
    application`` (i.e. this partner provisioned the team for this user, attributed
    at create time) AND the team lives in the same organization as ``base_team_id``
    AND the user still has team-level access. This is partner-agnostic, not
    Stripe-specific: ``stripe_project_id`` is the (legacily named) external project
    id every partner sets, always written alongside ``application`` in
    ``resolve_or_create_project_team``, so the ``application`` filter already
    implies a provisioned team. The organization filter pins the token to the
    authorization context:
    a partner with OAuth grants in multiple orgs for the same user must not be
    able to reach an org-B team via an org-A token just because the user happens
    to be a member of both.

    Returns ``[]`` when ``application`` is None (legacy refresh tokens with no
    app binding). A partner-unattributed token cannot be safely scoped, so it
    gets no teams and the holder must re-authorize. Falling through would let
    ``filter(application=None)`` match every TPC row with NULL application
    across every partner.

    Returns ``[]`` if ``base_team_id`` no longer resolves to a team the user
    can access; stale scope must not grant ongoing access after ACL revocation
    or org removal.
    """
    if application is None:
        return []

    try:
        base_team = Team.objects.select_related("organization").get(id=base_team_id)
    except Team.DoesNotExist:
        return []
    if not user_can_access_team(user, base_team):
        return []

    candidate_team_ids = set(
        TeamProvisioningConfig.objects.filter(
            application=application,
            team__organization_id=base_team.organization_id,
        ).values_list("team_id", flat=True)
    )
    candidate_team_ids.add(base_team_id)

    granted: set[int] = {base_team_id}
    other_teams = Team.objects.select_related("organization").filter(
        id__in=candidate_team_ids - {base_team_id},
    )
    for team in other_teams:
        if user_can_access_team(user, team):
            granted.add(team.id)

    # sorted() only for deterministic test assertions and log diffs; scope order is not a correctness requirement
    return sorted(granted)


def ensure_team_in_token_scopes(
    access_token: OAuthAccessToken, scoped_teams: list[int], team: Team
) -> tuple[Team, list[int]]:
    if team.id in scoped_teams:
        return team, scoped_teams
    add_team_to_token_scopes(access_token, team.id)
    return team, [*scoped_teams, team.id]


def add_team_to_token_scopes(access_token: OAuthAccessToken, team_id: int) -> None:
    with transaction.atomic():
        locked_access_token = OAuthAccessToken.objects.select_for_update().get(pk=access_token.pk)
        teams = list(locked_access_token.scoped_teams or [])
        if team_id not in teams:
            teams.append(team_id)
            locked_access_token.scoped_teams = teams
            locked_access_token.save(update_fields=["scoped_teams"])
            access_token.scoped_teams = teams

        refresh_tokens = OAuthRefreshToken.objects.select_for_update().filter(access_token=locked_access_token)
        for rt in refresh_tokens:
            rt_teams = list(rt.scoped_teams or [])
            if team_id not in rt_teams:
                rt_teams.append(team_id)
                rt.scoped_teams = rt_teams
                rt.save(update_fields=["scoped_teams"])


def remove_team_from_token_scopes(access_token: OAuthAccessToken, team_id: int) -> None:
    """Strip ``team_id`` from every access/refresh token for this partner+user combo.

    Removing a resource has to revoke access for any *other* live token the same
    partner installation might be holding for the same user (e.g. a separate
    bearer issued via a prior OAuth grant that still has the team in scope).
    Touching only the calling ``access_token`` would let the partner continue
    operating on the team via a sibling token after `remove` returned, since
    operational endpoints accept any team currently in ``scoped_teams``.

    Atomic so a refresh token can never be left with the removed team still in
    scope while the access token has it stripped — otherwise the orchestrator
    could refresh and replay the removed team right back into scope.
    """
    application = access_token.application
    user = access_token.user
    if application is None or user is None:
        # Defensive: a provisioning bearer token without an app/user shouldn't
        # exist in practice, but fall back to the single-token strip if it does.
        application_filter: dict[str, object] = {"pk": access_token.pk}
        user_filter: dict[str, object] = {}
    else:
        application_filter = {"application": application, "user": user}
        user_filter = {"application": application, "user": user}

    with transaction.atomic():
        access_tokens = list(
            OAuthAccessToken.objects.select_for_update()
            .filter(scoped_teams__contains=[team_id], **application_filter)
            .order_by("pk")
        )
        for at in access_tokens:
            remaining = [t for t in (at.scoped_teams or []) if t != team_id]
            refresh_tokens = OAuthRefreshToken.objects.select_for_update().filter(access_token=at)
            if not remaining:
                refresh_tokens.update(access_token=None, revoked=timezone.now(), scoped_teams=[])
                at.delete()
                continue
            at.scoped_teams = remaining
            at.save(update_fields=["scoped_teams"])
            for rt in refresh_tokens:
                rt.scoped_teams = [t for t in (rt.scoped_teams or []) if t != team_id]
                rt.save(update_fields=["scoped_teams"])

        if user_filter:
            # Orphan refresh tokens (where the access token was already rotated
            # or deleted) still carry scope. Strip the team from those too.
            orphan_refresh = OAuthRefreshToken.objects.select_for_update().filter(
                scoped_teams__contains=[team_id],
                access_token__isnull=True,
                revoked__isnull=True,
                **user_filter,
            )
            for rt in orphan_refresh:
                rt.scoped_teams = [t for t in (rt.scoped_teams or []) if t != team_id]
                rt.save(update_fields=["scoped_teams"])


def get_available_teams_for_user(user: User) -> list[dict[str, object]]:
    """Return the user's non-demo teams for inclusion in the token exchange response.

    Access-checked per team like the scoping paths: org membership alone would
    otherwise expose the names of teams an advanced-permissions org restricts,
    and list teams the partner can never be scoped to.
    """
    org_ids = list(user.organization_memberships.values_list("organization_id", flat=True))
    teams = Team.objects.filter(organization_id__in=org_ids, is_demo=False).select_related("organization")
    return [
        {
            "id": team.id,
            "name": team.name,
            "organization_id": str(team.organization_id),
            "organization_name": team.organization.name if team.organization else "",
        }
        for team in teams
        if user_can_access_team(user, team)
    ]
