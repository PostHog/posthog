from collections import defaultdict
from collections.abc import Collection

from django.db import models

from posthog.models.organization import OrganizationMembership
from posthog.models.utils import UUIDModel

# Email notification settings an organization may enforce, mapped to what a scope ID means for
# each. Deliberately an allowlist rather than "everything in Notifications minus a few":
#
# - Security alerts are absent, because losing sight of an exposed API key is an account-security
#   problem rather than a notification preference.
# - The realtime in-app map is absent, because v1 governs email only.
# - `data_pipeline_error_threshold` is absent, because it holds a rate rather than a switch.
LOCKABLE_NOTIFICATION_SETTINGS: dict[str, str] = {
    "plugin_disabled": "",
    "pipeline_notifications_disabled": "pipeline",
    "all_weekly_digest_disabled": "",
    "project_weekly_digest_disabled": "team",
    "error_tracking_issue_assigned": "",
    "error_tracking_weekly_digest": "",
    "error_tracking_weekly_digest_project_enabled": "team",
    "web_analytics_weekly_digest": "",
    "web_analytics_weekly_digest_project_enabled": "team",
    "discussions_mentioned": "",
    "materialized_view_sync_failed": "",
    "materialized_view_sync_failed_daily": "",
    "materialized_view_sync_failed_immediate": "",
    "organization_member_join_email_disabled": "organization",
}


class OrganizationMemberNotificationLock(UUIDModel):
    """An email notification setting an organization enforces on its members.

    The lock carries the value, and the member's own stored preference is left untouched, so
    removing a lock restores whatever the member had chosen. Send-time resolution order is
    member lock, then all-members lock, then the member's own setting, then the default.
    """

    # db_constraint=False on both FKs: posthog_organization is read on nearly every request, and
    # adding a real FK constraint takes a lock on the parent that queues behind live writes.
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="member_notification_locks",
        db_constraint=False,
    )
    # Null means the lock applies to every member of the organization, including those who join
    # later. A row naming a membership overrides the organization-wide row for that member.
    organization_membership = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="notification_locks",
        null=True,
        blank=True,
        db_constraint=False,
    )
    setting = models.CharField(max_length=64)
    # Identifies what the setting applies to when it is not a single switch: a team ID for the
    # per-project digests, a pipeline ID for pipeline failure emails. Empty means the setting
    # itself. Empty rather than null so the unique constraints below can compare it.
    scope_id = models.CharField(max_length=160, default="", db_default="", blank=True)
    locked_value = models.BooleanField()
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Split in two because Postgres treats null memberships as distinct, which would let
            # an organization accumulate duplicate all-members locks for one setting.
            models.UniqueConstraint(
                fields=["organization", "setting", "scope_id"],
                condition=models.Q(organization_membership__isnull=True),
                name="unique_org_wide_notification_lock",
            ),
            models.UniqueConstraint(
                fields=["organization", "organization_membership", "setting", "scope_id"],
                condition=models.Q(organization_membership__isnull=False),
                name="unique_member_notification_lock",
            ),
        ]
        indexes = [models.Index(fields=["organization", "setting"])]

    def __str__(self) -> str:
        target = self.organization_membership_id or "all members"
        return f"{self.setting}={self.locked_value} for {target}"


def notification_locks_for_users(user_ids: Collection[int]) -> dict[int, dict[tuple[str, str], bool]]:
    """Locks in force for each of these users, keyed by (setting, scope_id).

    A row naming the user's membership beats an organization-wide row for the same setting. These
    settings are stored once per user rather than once per membership, so a user who belongs to
    several organizations collects the locks of all of them.
    """
    memberships = list(
        OrganizationMembership.objects.filter(user_id__in=user_ids).values("id", "user_id", "organization_id")
    )
    if not memberships:
        return {}

    locks = OrganizationMemberNotificationLock.objects.filter(
        organization_id__in={membership["organization_id"] for membership in memberships}
    ).values("organization_id", "organization_membership_id", "setting", "scope_id", "locked_value")

    org_wide: dict[str, dict[tuple[str, str], bool]] = defaultdict(dict)
    per_membership: dict[str, dict[tuple[str, str], bool]] = defaultdict(dict)
    for lock in locks:
        key = (lock["setting"], lock["scope_id"] or "")
        if lock["organization_membership_id"] is None:
            org_wide[str(lock["organization_id"])][key] = lock["locked_value"]
        else:
            per_membership[str(lock["organization_membership_id"])][key] = lock["locked_value"]

    by_user: dict[int, dict[tuple[str, str], bool]] = defaultdict(dict)
    for membership in memberships:
        by_user[membership["user_id"]].update(org_wide.get(str(membership["organization_id"]), {}))
        by_user[membership["user_id"]].update(per_membership.get(str(membership["id"]), {}))
    return dict(by_user)


def effective_notification_settings(user, locks: dict[tuple[str, str], bool] | None = None) -> dict:
    """What this user's notification settings actually resolve to once locks apply.

    Pass `locks` when resolving many users at once, so a fan-out over an organization's members
    does not run one lock query per member. `notification_locks_for_users` returns them in the
    right shape.
    """
    if locks is None:
        locks = notification_locks_for_users([user.id]).get(user.id, {})
    return apply_notification_locks(user.notification_settings, locks)


def apply_notification_locks(settings: dict, locks: dict[tuple[str, str], bool]) -> dict:
    """The member's stored settings with their organization's locks laid over the top.

    The stored settings are never modified, so removing a lock restores whatever the member chose.
    """
    if not locks:
        return settings

    merged = dict(settings)
    for (setting, scope_id), value in locks.items():
        if not scope_id:
            merged[setting] = value
            continue
        scoped = dict(merged.get(setting) or {})
        scoped[scope_id] = value
        merged[setting] = scoped
    return merged
