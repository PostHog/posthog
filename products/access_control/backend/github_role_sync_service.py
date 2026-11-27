from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Expression, Prefetch, QuerySet, Subquery
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Lower
from django.utils import timezone

import structlog
from social_django.models import UserSocialAuth

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.integrations import CrossTeamFilter, IntegrationManager
from posthog.integrations.contracts import IntegrationRecord
from posthog.models import OrganizationMembership, Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserIntegration

from products.access_control.backend.facade.contracts import (
    ExternalRoleReference,
    GitHubRoleSyncOutcome,
    RoleMembershipDrift,
    RoleSyncActionMode,
    RoleSyncMode,
)
from products.access_control.backend.github_role_sync import (
    ExistingReferenceRecord,
    ExistingRoleRecord,
    GitHubOrgRoleSyncPlan,
    GitHubTeamSnapshot,
    PlannedOrphanUpdate,
    PlannedReferenceUpdate,
    compute_role_membership_drift,
    desired_user_ids_for_logins,
    normalize_member_logins,
    plan_github_org_role_sync,
)
from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.models.role_external_reference import RoleExternalReference

logger = structlog.get_logger(__name__)

GITHUB_PROVIDER = "github"
_TEAM_PAGE_SIZE = 100
_MAX_TEAM_PAGES = 20
_IDENTITY_PAGE_SIZE = 500


class ExternalRoleReferenceNotFoundError(LookupError):
    pass


@frozen
class _OrgMemberIdentityMap:
    login_to_user_id: Mapping[str, int]
    membership_id_by_user_id: Mapping[int, UUID]


@frozen
class _LoadedOrgRoleState:
    roles: tuple[ExistingRoleRecord, ...]
    references: tuple[ExistingReferenceRecord, ...]


@frozen
class _FetchedGitHubSnapshots:
    snapshots: tuple[GitHubTeamSnapshot, ...] | None
    missing_permission: bool


def to_external_role_reference_dto(row: RoleExternalReference) -> ExternalRoleReference:
    raw_logins = row.provider_member_logins
    logins_tuple = (
        tuple(str(item).lower() for item in raw_logins if isinstance(item, str))
        if isinstance(raw_logins, list)
        else None
    )
    return ExternalRoleReference(
        id=row.id,
        provider=row.provider,
        provider_organization_id=row.provider_organization_id,
        provider_role_id=row.provider_role_id,
        provider_role_slug=row.provider_role_slug,
        provider_role_name=row.provider_role_name,
        role_id=row.role_id,
        role_name=row.role.name,
        sync_mode=RoleSyncMode(row.sync_mode),
        role_created_by_sync=row.role_created_by_sync,
        provider_member_logins=logins_tuple,
        orphaned_at=row.orphaned_at,
        last_synced_at=row.last_synced_at,
    )


def _filter_json_login_lc(qs: QuerySet, field_path: str, logins_lower: frozenset[str]) -> QuerySet:
    column, *middle_keys, final_key = field_path.split("__")
    expr: str | Expression = column
    for key in middle_keys:
        expr = KeyTransform(key, expr)
    return qs.annotate(_login_lc=Lower(KeyTextTransform(final_key, expr))).filter(_login_lc__in=sorted(logins_lower))


def _iter_team_github_identity_rows(created_by_ids: Sequence[int]) -> Iterator[IntegrationRecord]:
    if not created_by_ids:
        return
    after_id: int | None = None
    while True:
        page = IntegrationManager.github.any.list_across_teams(
            CrossTeamFilter(
                created_by_ids=tuple(created_by_ids),
                has_config_key="connecting_user_github_login",
                limit=_IDENTITY_PAGE_SIZE,
                after_id=after_id,
            )
        )
        for row in page:
            if row.created_by_id is not None and row.config.get("connecting_user_github_login") is not None:
                yield row
        if len(page) < _IDENTITY_PAGE_SIZE:
            return
        after_id = page[-1].id


def _github_identity_prefetches() -> tuple[Prefetch, ...]:
    return (
        Prefetch(
            "integrations",
            UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.GITHUB),
            to_attr="_prefetched_github_user_integrations",
        ),
        Prefetch("social_auth", UserSocialAuth.objects.filter(provider="github")),
    )


def _candidate_org_user_ids_for_logins(
    organization_id: UUID,
    member_user_ids: Sequence[int],
    logins_lower: frozenset[str],
) -> set[int]:
    if not logins_lower or not member_user_ids:
        return set()
    member_subquery = Subquery(OrganizationMembership.objects.filter(organization_id=organization_id).values("user_id"))
    candidates: set[int] = set(
        _filter_json_login_lc(
            UserSocialAuth.objects.filter(provider="github", user_id__in=member_subquery),
            "extra_data__login",
            logins_lower,
        ).values_list("user_id", flat=True)
    )
    candidates.update(
        _filter_json_login_lc(
            UserIntegration.objects.filter(kind=UserIntegration.IntegrationKind.GITHUB, user_id__in=member_subquery),
            "config__github_user__login",
            logins_lower,
        ).values_list("user_id", flat=True)
    )
    for row in _iter_team_github_identity_rows(member_user_ids):
        login = row.config.get("connecting_user_github_login")
        if isinstance(login, str) and login.lower() in logins_lower:
            candidates.add(row.created_by_id)  # type: ignore[arg-type]
    return candidates


def _resolve_org_github_identities(
    organization_id: UUID,
    wanted_logins: Iterable[str],
) -> _OrgMemberIdentityMap:
    memberships = dict(
        OrganizationMembership.objects.filter(organization_id=organization_id).values_list("user_id", "id")
    )
    logins_lower = frozenset(normalize_member_logins(list(wanted_logins)))
    if not memberships or not logins_lower:
        return _OrgMemberIdentityMap(login_to_user_id={}, membership_id_by_user_id=memberships)

    candidate_ids = _candidate_org_user_ids_for_logins(organization_id, list(memberships.keys()), logins_lower)
    if not candidate_ids:
        return _OrgMemberIdentityMap(login_to_user_id={}, membership_id_by_user_id=memberships)

    users = list(
        User.objects.filter(id__in=candidate_ids).prefetch_related(*_github_identity_prefetches()).order_by("id")
    )
    team_rows_by_user: dict[int, list[IntegrationRecord]] = {user.id: [] for user in users}
    for row in _iter_team_github_identity_rows(list(team_rows_by_user.keys())):
        if row.created_by_id in team_rows_by_user:
            team_rows_by_user[row.created_by_id].append(row)

    login_to_user_id: dict[str, int] = {}
    for user in users:
        user._prefetched_github_integrations = team_rows_by_user[user.id]
        raw_login = user.get_github_login()
        if raw_login and (normalized := raw_login.lower()) in logins_lower and user.id in memberships:
            login_to_user_id.setdefault(normalized, user.id)
    return _OrgMemberIdentityMap(login_to_user_id=login_to_user_id, membership_id_by_user_id=memberships)


def _load_existing_org_state(
    organization_id: UUID,
) -> _LoadedOrgRoleState:
    roles = list(Role.objects.filter(organization_id=organization_id).order_by("name", "id"))
    role_ids = [role.id for role in roles]
    members_by_role: dict[UUID, set[int]] = defaultdict(set)
    if role_ids:
        for role_id, user_id in (
            RoleMembership.objects.filter(role_id__in=role_ids, role__organization_id=organization_id)
            .valid_for_authorization()
            .values_list("role_id", "user_id")
        ):
            members_by_role[role_id].add(user_id)

    role_records = tuple(
        ExistingRoleRecord(
            id=role.id,
            name=role.name,
            member_user_ids=frozenset(members_by_role.get(role.id, set())),
        )
        for role in roles
    )
    ref_rows = (
        RoleExternalReference.objects.filter(organization_id=organization_id, provider=GITHUB_PROVIDER)
        .select_related("role")
        .order_by("created_at", "id")
    )
    ref_records = tuple(
        ExistingReferenceRecord(
            id=row.id,
            provider_organization_id=row.provider_organization_id,
            provider_role_id=row.provider_role_id,
            provider_role_slug=row.provider_role_slug,
            provider_role_name=row.provider_role_name,
            role_id=row.role_id,
            role_name=row.role.name,
            sync_mode=RoleSyncMode(row.sync_mode),
            role_created_by_sync=row.role_created_by_sync,
            provider_member_logins=(
                tuple(str(item).lower() for item in row.provider_member_logins if isinstance(item, str))
                if isinstance(row.provider_member_logins, list)
                else None
            ),
            orphaned_at=row.orphaned_at,
            last_synced_at=row.last_synced_at,
        )
        for row in ref_rows
    )
    return _LoadedOrgRoleState(roles=role_records, references=ref_records)


def _reconcile_role_members(
    *,
    organization_id: UUID,
    role_id: UUID,
    desired_user_ids: frozenset[int],
    membership_id_by_user_id: Mapping[int, UUID],
) -> None:
    existing_by_user = {
        membership.user_id: membership
        for membership in RoleMembership.objects.filter(role_id=role_id, role__organization_id=organization_id)
    }
    for user_id, membership in existing_by_user.items():
        if user_id not in desired_user_ids:
            membership.delete()

    for user_id in sorted(desired_user_ids):
        org_member_id = membership_id_by_user_id.get(user_id)
        if org_member_id is None:
            continue
        existing = existing_by_user.get(user_id)
        if existing is not None:
            if existing.organization_member_id != org_member_id:
                existing.organization_member_id = org_member_id
                existing.save(update_fields=["organization_member_id"])
            continue
        RoleMembership.objects.create(
            role_id=role_id,
            user_id=user_id,
            organization_member_id=org_member_id,
        )


def _apply_orphan_operations(
    *,
    organization_id: UUID,
    orphan_references: Sequence[PlannedOrphanUpdate],
    synced_at: datetime,
) -> None:
    for orphan_op in orphan_references:
        updates: dict[str, Any] = {}
        if orphan_op.mark_orphaned:
            updates["orphaned_at"] = synced_at
        if orphan_op.clear_slug:
            updates["provider_role_slug"] = None
        if updates:
            RoleExternalReference.objects.filter(
                id=orphan_op.reference_id,
                organization_id=organization_id,
            ).update(**updates)


def _apply_update_operations(
    *,
    organization_id: UUID,
    update_references: Sequence[PlannedReferenceUpdate],
    membership_id_by_user_id: Mapping[int, UUID],
    synced_at: datetime,
) -> None:
    for update_op in update_references:
        ref_updates: dict[str, Any] = {
            "provider_role_id": update_op.provider_role_id,
            "provider_role_slug": update_op.provider_role_slug,
            "provider_role_name": update_op.provider_role_name,
            "provider_member_logins": list(update_op.provider_member_logins),
            "last_synced_at": synced_at,
        }
        if update_op.clear_orphaned:
            ref_updates["orphaned_at"] = None
        RoleExternalReference.objects.filter(
            id=update_op.reference_id,
            organization_id=organization_id,
        ).update(**ref_updates)

        if update_op.rename_role_to is not None:
            Role.objects.filter(id=update_op.role_id, organization_id=organization_id).update(
                name=update_op.rename_role_to
            )
        if update_op.reconcile_members:
            _reconcile_role_members(
                organization_id=organization_id,
                role_id=update_op.role_id,
                desired_user_ids=update_op.desired_user_ids,
                membership_id_by_user_id=membership_id_by_user_id,
            )


def _execute_sync_plan(
    *,
    organization_id: UUID,
    plan: GitHubOrgRoleSyncPlan,
    membership_id_by_user_id: Mapping[int, UUID],
    synced_at: datetime,
) -> GitHubRoleSyncOutcome:
    with transaction.atomic():
        # Clear colliding slugs on orphaned rows first so active rows can claim them cleanly.
        _apply_orphan_operations(
            organization_id=organization_id,
            orphan_references=plan.orphan_references,
            synced_at=synced_at,
        )
        _apply_update_operations(
            organization_id=organization_id,
            update_references=plan.update_references,
            membership_id_by_user_id=membership_id_by_user_id,
            synced_at=synced_at,
        )

        for proposal in plan.create_proposals:
            RoleExternalReference.objects.create(
                organization_id=organization_id,
                role_id=proposal.role_id,
                provider=GITHUB_PROVIDER,
                provider_organization_id=proposal.provider_organization_id,
                provider_role_id=proposal.provider_role_id,
                provider_role_slug=proposal.provider_role_slug,
                provider_role_name=proposal.provider_role_name,
                sync_mode=RoleExternalReference.SyncMode.PROPOSED,
                role_created_by_sync=False,
                provider_member_logins=list(proposal.provider_member_logins),
                last_synced_at=synced_at,
            )

        for creation in plan.create_roles:
            role = Role.objects.create(organization_id=organization_id, name=creation.role_name)
            RoleExternalReference.objects.create(
                organization_id=organization_id,
                role=role,
                provider=GITHUB_PROVIDER,
                provider_organization_id=creation.provider_organization_id,
                provider_role_id=creation.provider_role_id,
                provider_role_slug=creation.provider_role_slug,
                provider_role_name=creation.provider_role_name,
                sync_mode=RoleExternalReference.SyncMode.AUTO,
                role_created_by_sync=True,
                provider_member_logins=list(creation.provider_member_logins),
                last_synced_at=synced_at,
            )
            _reconcile_role_members(
                organization_id=organization_id,
                role_id=role.id,
                desired_user_ids=creation.member_user_ids,
                membership_id_by_user_id=membership_id_by_user_id,
            )

    return GitHubRoleSyncOutcome(
        created_roles=len(plan.create_roles),
        updated_roles=len(plan.update_references),
        proposed_roles=len(plan.create_proposals),
        orphaned_references=sum(1 for item in plan.orphan_references if item.mark_orphaned),
        skipped_missing_members_permission=False,
    )


def _integration_lacks_members_permission(record: IntegrationRecord) -> bool:
    permissions = record.config.get("permissions")
    return isinstance(permissions, Mapping) and "members" not in permissions


def _integration_is_github_organization(record: IntegrationRecord) -> bool:
    account = record.config.get("account")
    if not isinstance(account, Mapping):
        return False
    name = account.get("name")
    account_type = account.get("type")
    if not isinstance(name, str) or not name.strip():
        return False
    return account_type != "User"


def _fetch_github_org_snapshots(
    github: GitHubIntegration,
    github_org: str,
) -> _FetchedGitHubSnapshots:
    raw_teams: list[dict[str, Any]] = []
    offset = 0
    for _ in range(_MAX_TEAM_PAGES):
        try:
            page, has_more = github.list_teams(limit=_TEAM_PAGE_SIZE, offset=offset)
        except GitHubIntegrationError:
            return _FetchedGitHubSnapshots(snapshots=None, missing_permission=True)
        raw_teams.extend(page)
        if not has_more or not page:
            break
        offset += _TEAM_PAGE_SIZE

    snapshots: list[GitHubTeamSnapshot] = []
    for entry in raw_teams:
        slug = str(entry.get("slug") or "").strip().lower()
        name = str(entry.get("name") or slug).strip()
        team_id = entry.get("id")
        if not slug or team_id is None:
            continue
        members_resp = github.list_team_members(github_org, slug)
        if not members_resp.get("success"):
            if members_resp.get("status_code") in (403, 404):
                return _FetchedGitHubSnapshots(snapshots=None, missing_permission=True)
            logger.warning("access_control.github_role_sync.team_members_failed", org=github_org, slug=slug)
            return _FetchedGitHubSnapshots(snapshots=None, missing_permission=False)
        raw_logins = members_resp.get("logins") or []
        snapshots.append(
            GitHubTeamSnapshot(
                provider_role_id=str(team_id),
                slug=slug,
                name=name,
                member_logins=normalize_member_logins(raw_logins),
            )
        )
    return _FetchedGitHubSnapshots(snapshots=tuple(snapshots), missing_permission=False)


def _org_github_integrations(organization_id: UUID) -> dict[str, IntegrationRecord]:
    team_ids = tuple(Team.objects.filter(organization_id=organization_id).values_list("id", flat=True))
    if not team_ids:
        return {}
    by_github_org: dict[str, IntegrationRecord] = {}
    for record in IntegrationManager.github.oauth.list_across_teams(CrossTeamFilter(team_ids=team_ids)):
        if not _integration_is_github_organization(record):
            continue
        org_login = str(record.config["account"]["name"]).strip().lower()
        existing = by_github_org.get(org_login)
        # Prefer an installation row that explicitly carries `members` permission when several exist.
        if existing is None or (
            _integration_lacks_members_permission(existing) and not _integration_lacks_members_permission(record)
        ):
            by_github_org[org_login] = record
    return by_github_org


def _reconcile_snapshots_for_org(
    *,
    organization_id: UUID,
    github_org: str,
    snapshots: Sequence[GitHubTeamSnapshot],
    complete_org_team_list: bool,
) -> GitHubRoleSyncOutcome:
    all_logins = {login for team in snapshots for login in team.member_logins}
    identities = _resolve_org_github_identities(organization_id, all_logins)
    loaded = _load_existing_org_state(organization_id)
    plan = plan_github_org_role_sync(
        github_organization=github_org,
        github_teams=snapshots,
        existing_roles=loaded.roles,
        existing_references=loaded.references,
        login_to_user_id=identities.login_to_user_id,
        complete_org_team_list=complete_org_team_list,
    )
    return _execute_sync_plan(
        organization_id=organization_id,
        plan=plan,
        membership_id_by_user_id=identities.membership_id_by_user_id,
        synced_at=timezone.now(),
    )


def sync_organization_github_roles(
    *,
    organization_id: UUID,
    priority: Priority = Priority.BATCH,
) -> GitHubRoleSyncOutcome:
    integrations_by_org = _org_github_integrations(organization_id)
    if not integrations_by_org:
        return GitHubRoleSyncOutcome(
            created_roles=0,
            updated_roles=0,
            proposed_roles=0,
            orphaned_references=0,
            skipped_missing_members_permission=False,
        )

    created = 0
    updated = 0
    proposed = 0
    orphaned = 0
    missing_permission = False

    for github_org, record in integrations_by_org.items():
        if _integration_lacks_members_permission(record):
            missing_permission = True
            continue
        github = GitHubIntegration(record, source="github_role_sync", priority=priority)
        org_account_name = str(record.config["account"]["name"]).strip()
        fetched = _fetch_github_org_snapshots(github, org_account_name)
        if fetched.missing_permission:
            missing_permission = True
            continue
        if fetched.snapshots is None:
            continue
        outcome = _reconcile_snapshots_for_org(
            organization_id=organization_id,
            github_org=github_org,
            snapshots=fetched.snapshots,
            complete_org_team_list=True,
        )
        created += outcome.created_roles
        updated += outcome.updated_roles
        proposed += outcome.proposed_roles
        orphaned += outcome.orphaned_references

    return GitHubRoleSyncOutcome(
        created_roles=created,
        updated_roles=updated,
        proposed_roles=proposed,
        orphaned_references=orphaned,
        skipped_missing_members_permission=missing_permission,
    )


def sync_single_github_team_webhook(
    *,
    installation_id: str,
    action: str,
    github_org_login: str,
    github_team_id: int,
    github_team_slug: str,
    github_team_name: str,
) -> None:
    records = IntegrationManager.github.oauth.list_by_external_id(installation_id)
    if not records:
        return
    team_ids = [record.team_id for record in records]
    org_by_team = dict(Team.objects.filter(id__in=team_ids).values_list("id", "organization_id"))
    record_by_posthog_org: dict[UUID, IntegrationRecord] = {}
    for record in records:
        if (posthog_org_id := org_by_team.get(record.team_id)) is not None:
            record_by_posthog_org.setdefault(posthog_org_id, record)

    if not record_by_posthog_org:
        return

    normalized_org = github_org_login.strip().lower()
    now = timezone.now()
    if action == "deleted":
        for posthog_org_id in record_by_posthog_org:
            RoleExternalReference.objects.filter(
                organization_id=posthog_org_id,
                provider=GITHUB_PROVIDER,
                provider_organization_id__iexact=normalized_org,
                provider_role_id=str(github_team_id),
                orphaned_at__isnull=True,
            ).update(orphaned_at=now)
        return

    sample_record = next(iter(record_by_posthog_org.values()))
    if _integration_lacks_members_permission(sample_record):
        return
    github = GitHubIntegration(sample_record, source="github_role_sync_webhook", priority=Priority.BATCH)
    members_resp = github.list_team_members(github_org_login.strip(), github_team_slug.strip())
    if not members_resp.get("success"):
        logger.warning(
            "access_control.github_role_sync.webhook_members_failed",
            installation_id=installation_id,
            org=normalized_org,
            slug=github_team_slug,
        )
        return

    snapshot = GitHubTeamSnapshot(
        provider_role_id=str(github_team_id),
        slug=github_team_slug.strip().lower(),
        name=github_team_name.strip() or github_team_slug.strip(),
        member_logins=normalize_member_logins(members_resp.get("logins") or []),
    )
    for posthog_org_id in record_by_posthog_org:
        _reconcile_snapshots_for_org(
            organization_id=posthog_org_id,
            github_org=normalized_org,
            snapshots=(snapshot,),
            complete_org_team_list=False,
        )


def _refresh_reference_logins_if_missing(
    organization_id: UUID,
    ref: RoleExternalReference,
) -> list[str] | None:
    if isinstance(ref.provider_member_logins, list):
        return [str(item).lower() for item in ref.provider_member_logins if isinstance(item, str)]
    if ref.provider != GITHUB_PROVIDER or not ref.provider_role_slug:
        return None
    record = _org_github_integrations(organization_id).get(ref.provider_organization_id.lower())
    if record is None or _integration_lacks_members_permission(record):
        return None
    github = GitHubIntegration(record, source="github_role_sync_apply", priority=Priority.NORMAL)
    org_name = str(record.config["account"]["name"]).strip()
    resp = github.list_team_members(org_name, ref.provider_role_slug)
    if not resp.get("success"):
        return None
    return list(normalize_member_logins(resp.get("logins") or []))


def apply_role_external_reference_sync(
    *,
    organization_id: UUID,
    reference_id: UUID,
    mode: RoleSyncActionMode,
) -> ExternalRoleReference:
    try:
        ref = RoleExternalReference.objects.select_related("role").get(
            id=reference_id,
            organization_id=organization_id,
        )
    except RoleExternalReference.DoesNotExist as exc:
        raise ExternalRoleReferenceNotFoundError(str(reference_id)) from exc

    if mode == RoleSyncActionMode.MANUAL:
        ref.sync_mode = RoleExternalReference.SyncMode.MANUAL
        ref.save(update_fields=["sync_mode", "updated_at"])
        return to_external_role_reference_dto(ref)

    logins = _refresh_reference_logins_if_missing(organization_id, ref)
    identities = _resolve_org_github_identities(organization_id, logins or ())
    next_mode = (
        RoleExternalReference.SyncMode.AUTO
        if mode == RoleSyncActionMode.AUTO
        else RoleExternalReference.SyncMode.MANUAL
    )
    now = timezone.now()

    with transaction.atomic():
        if logins is not None:
            desired_ids = desired_user_ids_for_logins(logins, identities.login_to_user_id)
            _reconcile_role_members(
                organization_id=organization_id,
                role_id=ref.role_id,
                desired_user_ids=desired_ids,
                membership_id_by_user_id=identities.membership_id_by_user_id,
            )
            ref.provider_member_logins = logins
            ref.last_synced_at = now
        ref.sync_mode = next_mode
        ref.save(update_fields=["sync_mode", "provider_member_logins", "last_synced_at", "updated_at"])

    return to_external_role_reference_dto(ref)


def compute_drift_by_reference_id(
    *,
    organization_id: UUID,
    reference_ids: Sequence[UUID],
) -> dict[UUID, RoleMembershipDrift]:
    if not reference_ids:
        return {}
    ref_rows = list(
        RoleExternalReference.objects.filter(
            organization_id=organization_id,
            id__in=list(reference_ids),
        ).values("id", "role_id", "provider_member_logins")
    )
    if not ref_rows:
        return {}
    role_ids = {row["role_id"] for row in ref_rows}
    members_by_role: dict[UUID, set[int]] = defaultdict(set)
    for role_id, user_id in (
        RoleMembership.objects.filter(role_id__in=role_ids, role__organization_id=organization_id)
        .valid_for_authorization()
        .values_list("role_id", "user_id")
    ):
        members_by_role[role_id].add(user_id)

    all_logins: set[str] = set()
    for row in ref_rows:
        raw_logins = row["provider_member_logins"]
        if isinstance(raw_logins, list):
            all_logins.update(str(item).lower() for item in raw_logins if isinstance(item, str))

    identities = _resolve_org_github_identities(organization_id, all_logins)
    return {
        row["id"]: compute_role_membership_drift(
            current_user_ids=frozenset(members_by_role.get(row["role_id"], set())),
            provider_member_logins=(
                [str(item) for item in row["provider_member_logins"] if isinstance(item, str)]
                if isinstance(row["provider_member_logins"], list)
                else None
            ),
            login_to_user_id=identities.login_to_user_id,
        )
        for row in ref_rows
    }


def list_organizations_with_github_team_sync_candidates() -> list[UUID]:
    """Organizations holding at least one GitHub org installation that can read team members."""
    records = IntegrationManager.github.oauth.list_across_teams(CrossTeamFilter(where={"account.type": "Organization"}))
    eligible_team_ids = [record.team_id for record in records if not _integration_lacks_members_permission(record)]
    if not eligible_team_ids:
        return []
    return list(Team.objects.filter(id__in=eligible_team_ids).values_list("organization_id", flat=True).distinct())
