from collections import defaultdict
from collections.abc import Collection
from uuid import UUID

from django.db import models

from posthog.dataclasses import frozen
from posthog.models.utils import UUIDModel

# What an organization may enforce, mapped to what a rule's scope ID means. An allowlist, so
# security alerts, the in-app map, and the master switches stay out of reach. A member who turns
# their own master switch off therefore cannot be reached by a project rule.
LOCKABLE_NOTIFICATION_SETTINGS: dict[str, str] = {
    "pipeline_notifications_disabled": "team",
    "project_weekly_digest_disabled": "team",
    "error_tracking_weekly_digest_project_enabled": "team",
    "web_analytics_weekly_digest_project_enabled": "team",
    "organization_member_join_email_disabled": "organization",
    "error_tracking_issue_assigned": "",
    "discussions_mentioned": "",
    "materialized_view_sync_failed": "",
    "materialized_view_sync_failed_daily": "",
    "materialized_view_sync_failed_immediate": "",
}

# Stored per pipeline but governed per project, so these cannot be merged into the stored map by
# key and are resolved where the failing pipeline's team is known.
PROJECT_RESOLVED_SETTINGS = frozenset({"pipeline_notifications_disabled"})


# nosemgrep: tuple-return-prefer-dataclass -- Django's `choices` contract is (value, label) pairs.
def lockable_setting_choices() -> list[tuple[str, str]]:
    # Callable so growing the allowlist doesn't generate a no-op migration.
    return [(setting, setting) for setting in sorted(LOCKABLE_NOTIFICATION_SETTINGS)]


@frozen
class GovernedSetting:
    """Which setting a rule decides, and what it applies to.

    Both parts are strings, so a bare tuple lets a caller swap them and silently match nothing,
    which would read as "no rule" and quietly stop enforcing one.
    """

    setting: str
    scope_id: str


class OrganizationMemberNotificationLock(UUIDModel):
    """An email notification setting an organization enforces on one of its members.

    The rule carries the value and the member's stored preference is left untouched, so removing a
    rule restores their own choice. Every rule names one person and one scope.
    """

    # db_constraint=False: posthog_organization is hot, and the FK constraint would lock it.
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="member_notification_locks",
        db_constraint=False,
    )
    organization_membership = models.ForeignKey(
        "posthog.OrganizationMembership",
        on_delete=models.CASCADE,
        related_name="notification_locks",
        db_constraint=False,
    )
    setting = models.CharField(max_length=64, choices=lockable_setting_choices)
    # A team ID, an organization ID, or empty for a single switch. See the allowlist above.
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
            models.UniqueConstraint(
                fields=["organization", "organization_membership", "setting", "scope_id"],
                name="unique_member_notification_lock",
            )
        ]
        indexes = [models.Index(fields=["organization", "setting"])]

    def __str__(self) -> str:
        return f"{self.setting}={self.locked_value} for membership {self.organization_membership_id}"


def notification_locks_for_users(
    user_ids: Collection[int], organization_id: str | UUID | None = None
) -> dict[int, dict[GovernedSetting, bool]]:
    """Rules in force for each user, keyed by (setting, scope_id).

    Pass `organization_id` when resolving rules for a notification one organization is sending, so
    that an organization only decides its own emails. Settings such as `discussions_mentioned` are
    stored once per user rather than per membership, so without this an admin of one organization
    would silence a shared member everywhere they work.

    Leave it out only where every rule affecting a person is wanted, such as showing that person
    what applies to them.
    """
    queryset = OrganizationMemberNotificationLock.objects.filter(organization_membership__user_id__in=user_ids)
    if organization_id is not None:
        queryset = queryset.filter(organization_id=organization_id)
    locks = queryset.values("organization_membership__user_id", "setting", "scope_id", "locked_value")

    by_user: dict[int, dict[GovernedSetting, bool]] = defaultdict(dict)
    for lock in locks:
        key = GovernedSetting(setting=lock["setting"], scope_id=lock["scope_id"] or "")
        by_user[lock["organization_membership__user_id"]][key] = lock["locked_value"]
    return dict(by_user)


def effective_notification_settings(user, locks: dict[GovernedSetting, bool] | None = None) -> dict:
    """This user's settings once their organization's rules apply.

    Pass `locks` when resolving many users, so a fan-out does not run one query per member.
    """
    if locks is None:
        locks = notification_locks_for_users([user.id]).get(user.id, {})
    return apply_notification_locks(user.notification_settings, locks)


def apply_notification_locks(settings: dict, locks: dict[GovernedSetting, bool]) -> dict:
    """Stored settings with the organization's rules laid over the top, leaving the stored ones intact."""
    if not locks:
        return settings

    merged = dict(settings)
    for governed, value in locks.items():
        if governed.setting in PROJECT_RESOLVED_SETTINGS:
            continue
        if not governed.scope_id:
            merged[governed.setting] = value
            continue
        scoped = dict(merged.get(governed.setting) or {})
        scoped[governed.scope_id] = value
        merged[governed.setting] = scoped
    return merged


def pipeline_lock_for_team(locks: dict[GovernedSetting, bool], team_id: int | None) -> bool | None:
    """The value an organization enforces for a project's pipeline failure emails, if any."""
    if team_id is None:
        return None
    return locks.get(GovernedSetting(setting="pipeline_notifications_disabled", scope_id=str(team_id)))
