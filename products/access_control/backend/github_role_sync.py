from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from posthog.dataclasses import frozen

from products.access_control.backend.facade.contracts import RoleMembershipDrift, RoleSyncMode
from products.access_control.backend.likely_role import RoleCandidate, RoleMatcher

_MAX_ROLE_NAME_LENGTH = 200


@frozen
class GitHubTeamSnapshot:
    provider_role_id: str
    slug: str
    name: str
    member_logins: tuple[str, ...]


@frozen
class ExistingRoleRecord:
    id: UUID
    name: str
    member_user_ids: frozenset[int]


@frozen
class ExistingReferenceRecord:
    id: UUID
    provider_organization_id: str
    provider_role_id: str
    provider_role_slug: str | None
    provider_role_name: str
    role_id: UUID
    role_name: str
    sync_mode: RoleSyncMode
    role_created_by_sync: bool
    provider_member_logins: tuple[str, ...] | None
    orphaned_at: datetime | None
    last_synced_at: datetime | None


@frozen
class PlannedRoleCreation:
    role_name: str
    provider_organization_id: str
    provider_role_id: str
    provider_role_slug: str
    provider_role_name: str
    provider_member_logins: tuple[str, ...]
    member_user_ids: frozenset[int]


@frozen
class PlannedReferenceProposal:
    role_id: UUID
    provider_organization_id: str
    provider_role_id: str
    provider_role_slug: str
    provider_role_name: str
    provider_member_logins: tuple[str, ...]


@frozen
class PlannedReferenceUpdate:
    reference_id: UUID
    role_id: UUID
    provider_role_id: str
    provider_role_slug: str
    provider_role_name: str
    provider_member_logins: tuple[str, ...]
    clear_orphaned: bool
    rename_role_to: str | None
    reconcile_members: bool
    desired_user_ids: frozenset[int]


@frozen
class PlannedOrphanUpdate:
    reference_id: UUID
    mark_orphaned: bool
    clear_slug: bool


@frozen
class GitHubOrgRoleSyncPlan:
    create_roles: tuple[PlannedRoleCreation, ...]
    create_proposals: tuple[PlannedReferenceProposal, ...]
    update_references: tuple[PlannedReferenceUpdate, ...]
    orphan_references: tuple[PlannedOrphanUpdate, ...]


def normalize_member_logins(logins: Sequence[str]) -> tuple[str, ...]:
    cleaned = {login.strip().lower() for login in logins if login and login.strip()}
    return tuple(sorted(cleaned))


def desired_user_ids_for_logins(
    member_logins: Sequence[str],
    login_to_user_id: Mapping[str, int],
) -> frozenset[int]:
    return frozenset(
        login_to_user_id[normalized]
        for login in member_logins
        if (normalized := login.strip().lower()) in login_to_user_id
    )


def compute_role_membership_drift(
    *,
    current_user_ids: frozenset[int],
    provider_member_logins: Sequence[str] | None,
    login_to_user_id: Mapping[str, int],
) -> RoleMembershipDrift:
    if provider_member_logins is None:
        return RoleMembershipDrift(
            has_drift=False,
            to_add_user_ids=frozenset(),
            to_remove_user_ids=frozenset(),
            provider_member_count=None,
            matched_posthog_member_count=0,
            current_role_member_count=len(current_user_ids),
        )

    normalized_logins = normalize_member_logins(provider_member_logins)
    desired_ids = desired_user_ids_for_logins(normalized_logins, login_to_user_id)
    to_add = desired_ids - current_user_ids
    to_remove = current_user_ids - desired_ids
    return RoleMembershipDrift(
        has_drift=bool(to_add or to_remove),
        to_add_user_ids=to_add,
        to_remove_user_ids=to_remove,
        provider_member_count=len(normalized_logins),
        matched_posthog_member_count=len(desired_ids),
        current_role_member_count=len(current_user_ids),
    )


def _choose_unique_role_name(
    *,
    preferred_name: str,
    team_slug: str,
    github_organization: str,
    reserved_names_lower: set[str],
) -> str:
    base = preferred_name.strip() or team_slug
    candidates = [
        base,
        f"{base} ({github_organization})",
        f"{base} ({github_organization}/{team_slug})",
    ]
    for candidate in candidates:
        bounded = candidate[:_MAX_ROLE_NAME_LENGTH]
        if bounded.lower() not in reserved_names_lower:
            reserved_names_lower.add(bounded.lower())
            return bounded

    counter = 2
    while True:
        suffix = f" ({counter})"
        bounded = f"{base[: _MAX_ROLE_NAME_LENGTH - len(suffix)]}{suffix}"
        if bounded.lower() not in reserved_names_lower:
            reserved_names_lower.add(bounded.lower())
            return bounded
        counter += 1


def _find_matching_reference(
    team: GitHubTeamSnapshot,
    references: Sequence[ExistingReferenceRecord],
    claimed_reference_ids: set[UUID],
) -> ExistingReferenceRecord | None:
    target_id = team.provider_role_id.lower()
    target_slug = team.slug.lower()
    for ref in references:
        if ref.id in claimed_reference_ids:
            continue
        if ref.provider_role_id.lower() == target_id:
            return ref
    for ref in references:
        if ref.id in claimed_reference_ids or ref.orphaned_at is not None:
            continue
        # Only upgrade manual slug-based references; never rebind a reference pinned to another numeric GitHub team ID.
        if ref.provider_role_id.isdigit():
            continue
        ref_slug = (ref.provider_role_slug or ref.provider_role_id).lower()
        if ref_slug == target_slug:
            return ref
    return None


def _maybe_rename_synced_role(
    ref: ExistingReferenceRecord,
    current_role: ExistingRoleRecord | None,
    desired_name: str,
    reserved_names_lower: set[str],
) -> str | None:
    if not ref.role_created_by_sync or current_role is None:
        return None
    cleaned = desired_name.strip()[:_MAX_ROLE_NAME_LENGTH]
    if not cleaned or cleaned == current_role.name:
        return None
    if cleaned.lower() != current_role.name.lower() and cleaned.lower() in reserved_names_lower:
        return None
    reserved_names_lower.discard(current_role.name.lower())
    reserved_names_lower.add(cleaned.lower())
    return cleaned


def _was_previously_synced(ref: ExistingReferenceRecord) -> bool:
    return (
        ref.last_synced_at is not None
        or ref.role_created_by_sync
        or ref.sync_mode in (RoleSyncMode.AUTO, RoleSyncMode.PROPOSED)
    )


def _plan_orphan_updates(
    *,
    references: Sequence[ExistingReferenceRecord],
    claimed_reference_ids: set[UUID],
    active_slugs_lower: set[str],
    complete_org_team_list: bool,
) -> tuple[PlannedOrphanUpdate, ...]:
    planned: list[PlannedOrphanUpdate] = []
    for ref in references:
        if ref.id in claimed_reference_ids:
            continue
        should_mark_orphaned = complete_org_team_list and ref.orphaned_at is None and _was_previously_synced(ref)
        is_orphaned = ref.orphaned_at is not None or should_mark_orphaned
        # Release the slug on an orphaned row when a newly created GitHub team reuses that slug.
        clear_slug = bool(
            is_orphaned and ref.provider_role_slug and ref.provider_role_slug.lower() in active_slugs_lower
        )
        if should_mark_orphaned or clear_slug:
            planned.append(
                PlannedOrphanUpdate(
                    reference_id=ref.id,
                    mark_orphaned=should_mark_orphaned,
                    clear_slug=clear_slug,
                )
            )
    return tuple(planned)


def plan_github_org_role_sync(
    *,
    github_organization: str,
    github_teams: Sequence[GitHubTeamSnapshot],
    existing_roles: Sequence[ExistingRoleRecord],
    existing_references: Sequence[ExistingReferenceRecord],
    login_to_user_id: Mapping[str, int],
    complete_org_team_list: bool,
) -> GitHubOrgRoleSyncPlan:
    """Pure reconciliation plan between a GitHub organization's teams and PostHog roles.

    Roles created by GitHub sync stay in ``AUTO`` mode and mirror GitHub membership. Pre-existing
    PostHog roles matched by name enter ``PROPOSED`` mode without mutating ``RoleMembership`` rows
    so RBAC grants are never widened without admin confirmation.
    """
    normalized_org = github_organization.strip().lower()
    org_refs = [ref for ref in existing_references if ref.provider_organization_id.lower() == normalized_org]
    roles_by_id = {role.id: role for role in existing_roles}
    reserved_names_lower = {role.name.lower() for role in existing_roles}

    sync_created_role_ids = {ref.role_id for ref in existing_references if ref.role_created_by_sync}
    manual_role_candidates = [
        RoleCandidate(id=role.id, name=role.name) for role in existing_roles if role.id not in sync_created_role_ids
    ]
    matcher = RoleMatcher(references=(), roles=manual_role_candidates)

    claimed_reference_ids: set[UUID] = set()
    active_slugs_lower: set[str] = set()
    create_roles: list[PlannedRoleCreation] = []
    create_proposals: list[PlannedReferenceProposal] = []
    update_references: list[PlannedReferenceUpdate] = []

    for team in github_teams:
        slug = team.slug.strip().lower()
        if not slug:
            continue
        active_slugs_lower.add(slug)
        logins = normalize_member_logins(team.member_logins)
        desired_ids = desired_user_ids_for_logins(logins, login_to_user_id)
        existing_ref = _find_matching_reference(team, org_refs, claimed_reference_ids)

        if existing_ref is not None:
            claimed_reference_ids.add(existing_ref.id)
            current_role = roles_by_id.get(existing_ref.role_id)
            rename_to = _maybe_rename_synced_role(existing_ref, current_role, team.name, reserved_names_lower)
            update_references.append(
                PlannedReferenceUpdate(
                    reference_id=existing_ref.id,
                    role_id=existing_ref.role_id,
                    provider_role_id=team.provider_role_id,
                    provider_role_slug=slug,
                    provider_role_name=team.name,
                    provider_member_logins=logins,
                    clear_orphaned=existing_ref.orphaned_at is not None,
                    rename_role_to=rename_to,
                    reconcile_members=existing_ref.sync_mode == RoleSyncMode.AUTO,
                    desired_user_ids=desired_ids,
                )
            )
            continue

        matched_manual_role = matcher.match(f"@{normalized_org}/{slug}")
        if matched_manual_role is not None:
            create_proposals.append(
                PlannedReferenceProposal(
                    role_id=matched_manual_role.id,
                    provider_organization_id=normalized_org,
                    provider_role_id=team.provider_role_id,
                    provider_role_slug=slug,
                    provider_role_name=team.name,
                    provider_member_logins=logins,
                )
            )
            continue

        role_name = _choose_unique_role_name(
            preferred_name=team.name,
            team_slug=slug,
            github_organization=normalized_org,
            reserved_names_lower=reserved_names_lower,
        )
        create_roles.append(
            PlannedRoleCreation(
                role_name=role_name,
                provider_organization_id=normalized_org,
                provider_role_id=team.provider_role_id,
                provider_role_slug=slug,
                provider_role_name=team.name,
                provider_member_logins=logins,
                member_user_ids=desired_ids,
            )
        )

    orphan_updates = _plan_orphan_updates(
        references=org_refs,
        claimed_reference_ids=claimed_reference_ids,
        active_slugs_lower=active_slugs_lower,
        complete_org_team_list=complete_org_team_list,
    )
    return GitHubOrgRoleSyncPlan(
        create_roles=tuple(create_roles),
        create_proposals=tuple(create_proposals),
        update_references=tuple(update_references),
        orphan_references=orphan_updates,
    )
