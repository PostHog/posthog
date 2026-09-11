from uuid import UUID

from django.db import connection, transaction

from structlog import get_logger

from products.approvals.backend.models import ApprovalPolicy

logger = get_logger(__name__)

# Each feature flag action and the experiment action that replaces it once experiment-owned flags
# leave `feature_flag.*` scope. Until then the experiment policies are mirrors: they are hidden from
# the API and nothing evaluates them, so organizations keep configuring flag policies only.
ACTION_MAP = {
    "feature_flag.enable": "experiment.launch",
    "feature_flag.disable": "experiment.pause",
    "feature_flag.update": "experiment.update",
}

SYNCED_ACTION_KEYS = frozenset(ACTION_MAP.values())

MIRRORED_FIELDS = (
    "conditions",
    "approver_config",
    "allow_self_approve",
    "bypass_org_membership_levels",
    "expires_after",
    "enabled",
    "created_by_id",
)

_SYNC_LOCK_KEY = "approvals:sync_experiment_policies"


def sync_experiment_policies() -> None:
    """Make the experiment policies an exact mirror of the feature flag policies.

    Creates a mirror for each new flag policy, overwrites a mirror whose flag policy changed, and
    deletes a mirror whose flag policy is gone. A one-off copy would drift in all three ways while
    organizations keep editing flag policies before the experiment actions take effect.

    Deleting orphans is safe because every row with a synced action key is a mirror: the API
    rejects those keys, so no person can create one.

    One run at a time holds a lock, and an overlapping run skips. The unique constraint cannot
    stop two runs from each inserting an organization-level mirror, because `team_id` is NULL there.
    """
    with transaction.atomic():
        if not _try_sync_lock():
            logger.info("sync_experiment_policies.skipped", reason="another run holds the lock")
            return

        created = updated = 0
        live: set[tuple[UUID, int | None, str]] = set()

        sources = ApprovalPolicy.objects.filter(action_key__in=ACTION_MAP).prefetch_related("bypass_roles")
        for source in sources:
            target_action = ACTION_MAP[source.action_key]
            live.add((source.organization_id, source.team_id, target_action))
            fields = {field: getattr(source, field) for field in MIRRORED_FIELDS}
            roles = {role.id for role in source.bypass_roles.all()}

            mirror, was_created = ApprovalPolicy.objects.get_or_create(
                organization_id=source.organization_id,
                team_id=source.team_id,
                action_key=target_action,
                defaults=fields,
            )
            if was_created:
                mirror.bypass_roles.set(roles)
                created += 1
                continue

            stale = [field for field, value in fields.items() if getattr(mirror, field) != value]
            if stale:
                for field in stale:
                    setattr(mirror, field, fields[field])
                mirror.save(update_fields=[*stale, "updated_at"])
            if set(mirror.bypass_roles.values_list("id", flat=True)) != roles:
                mirror.bypass_roles.set(roles)
                stale.append("bypass_roles")
            if stale:
                updated += 1

        orphans = [
            mirror
            for mirror in ApprovalPolicy.objects.filter(action_key__in=SYNCED_ACTION_KEYS)
            if (mirror.organization_id, mirror.team_id, mirror.action_key) not in live
        ]
        for orphan in orphans:
            orphan.delete()

    logger.info("sync_experiment_policies.complete", created=created, updated=updated, deleted=len(orphans))


def _try_sync_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", [_SYNC_LOCK_KEY])
        return cursor.fetchone()[0]
