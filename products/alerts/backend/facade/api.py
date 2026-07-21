import uuid
from typing import Literal
from zoneinfo import ZoneInfo

import structlog

from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.user_permissions import UserPermissions
from posthog.utils import relative_date_parse

from products.alerts.backend.destination_configs import (
    DESTINATION_TEMPLATE_IDS,
    AlertDestinationData,
    AlertDestinationValidationError,
    DestinationType,
    build_alert_destination_config,
    validate_destination_data,
)
from products.alerts.backend.destinations import (
    create_alert_destination_hog_functions,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.alerts.backend.email_notifications import send_alert_email
from products.alerts.backend.models.alert import AlertConfiguration

logger = structlog.get_logger(__name__)

SlackSnoozeOutcome = Literal["snoozed", "no_access", "disabled", "not_found"]


def get_alert_team_id(alert_id: uuid.UUID) -> int | None:
    """The team an alert belongs to, or None if no such alert exists.

    Lets callers outside this product (the Slack snooze-button handler) resolve an alert's team
    — to find its workspace integration, and for region-ownership routing — without importing
    the model directly.
    """
    # Slack webhook: no team context available yet — this lookup only resolves the team so the
    # caller can find the workspace integration; authorization is derived from the alert row in
    # snooze_alert_from_slack below, not from this lookup.
    # nosemgrep: idor-lookup-without-team
    return AlertConfiguration.objects.filter(id=alert_id).values_list("team_id", flat=True).first()


def snooze_alert_from_slack(alert_id: uuid.UUID, *, duration: str, user: User) -> SlackSnoozeOutcome:
    """Snooze an alert on behalf of a Slack "Snooze" button click.

    Owns all alert-side authorization and the mutation itself. `user` must already be confirmed
    as a member of the alert's Slack-connected organization by the caller — the alert_id and
    duration come from an untrusted Slack button value (user-editable hog function config), so
    every access decision here is re-derived from the alert row, never taken on trust from the
    caller.
    """
    try:
        # Slack webhook: no team context, and alert_id/duration come from an untrusted Slack
        # button value. Authorization is derived below from the alert row itself (project
        # membership + insight viewer access), never taken on trust from the caller.
        # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get
        alert = AlertConfiguration.objects.select_related("insight", "team").get(id=alert_id)
    except AlertConfiguration.DoesNotExist:
        return "not_found"

    # Mirrors TeamMemberAccessPermission (posthog/permissions.py): a non-admin member with no
    # explicit membership in a private project must be denied, even though they belong to the
    # organization. effective_membership_level falls back to the plain org membership level when
    # the organization doesn't have ACCESS_CONTROL, so this never false-denies on non-EE orgs.
    if UserPermissions(user).team(alert.team).effective_membership_level is None:
        logger.warning("alert_snooze_no_project_membership", alert_id=str(alert_id), user_id=user.id)
        return "no_access"

    # Project membership doesn't imply access to every insight in it — mirrors
    # _require_insight_viewer_access, the same check the alerts API itself uses.
    if not UserAccessControl(user, team=alert.team).check_access_level_for_object(alert.insight, "viewer"):
        logger.warning("alert_snooze_no_insight_access", alert_id=str(alert_id), user_id=user.id)
        return "no_access"

    if not alert.enabled:
        return "disabled"

    # always store snoozed_until as UTC time, as we look at current UTC time to check when to
    # run alerts — same call the alerts API uses so "1d" means the same thing everywhere.
    snoozed_until = relative_date_parse(duration, ZoneInfo("UTC"), increase=True, always_truncate=True)
    with ActingUserContext(user):
        alert.snooze(until=snoozed_until)

    return "snoozed"


__all__ = [
    "DESTINATION_TEMPLATE_IDS",
    "AlertDestinationData",
    "AlertDestinationValidationError",
    "DestinationType",
    "SlackSnoozeOutcome",
    "build_alert_destination_config",
    "create_alert_destination_hog_functions",
    "get_alert_team_id",
    "snooze_alert_from_slack",
    "soft_delete_alert_destinations",
    "soft_delete_all_alert_destinations",
    "send_alert_email",
    "validate_destination_data",
]
