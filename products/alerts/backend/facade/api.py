import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

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
    soft_delete_alert_destinations_for_alerts,
    soft_delete_all_alert_destinations,
)
from products.alerts.backend.email_notifications import send_alert_email
from products.alerts.backend.insight_alert_state_machine import apply_snooze
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.alerts.backend.presentation.views.alert_schedule_restriction import AlertScheduleRestriction
from products.alerts.backend.scheduling import validate_and_normalize_schedule_restriction

logger = structlog.get_logger(__name__)

SlackSnoozeOutcome = Literal["snoozed", "no_access", "disabled", "not_found", "invalid_until"]

# Mirrors the in-app SnoozeButton's DateFilter max — Slack's datetimepicker has no bounds of
# its own, so the cap has to live here.
SLACK_SNOOZE_MAX_DAYS = 31


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


def insight_ids_with_alerts(insight_ids: Collection[int]) -> set[int]:
    """Which of the given insights have at least one alert configured.

    Lets callers outside this product treat "an alert points at this insight" as a signal that
    something depends on it, without importing the model.
    """
    # Caller-supplied ids that are already team-scoped by the caller's own query; this only maps
    # ids to ids and returns no row data.
    # nosemgrep: idor-lookup-without-team
    return set(AlertConfiguration.objects.filter(insight_id__in=insight_ids).values_list("insight_id", flat=True))


def insight_alerts_prefetch(to_attr: str) -> Prefetch:
    """A ``Prefetch`` loading an insight's alerts in the shape ``serialize_insight_alerts`` needs.

    Callers add it to their insight queryset and read the alerts back off ``to_attr``. The
    select_related/prefetch_related shape belongs here because it follows AlertSerializer:
    that serializer emits threshold and subscribed_users per alert, so without them every
    alert in the response costs two extra queries.
    """
    # Sets no team filter of its own: the prefetch is scoped by the insight queryset it is
    # attached to, and an alert always belongs to its insight's team.
    # nosemgrep: idor-lookup-without-team
    queryset = AlertConfiguration.objects.select_related("created_by", "threshold").prefetch_related("subscribed_users")
    return Prefetch("alertconfiguration_set", queryset=queryset, to_attr=to_attr)


def delete_insight_alerts(insight_ids: Collection[int]) -> None:
    """Delete the alerts pointing at the given insights.

    Call this inside the transaction that deletes or hides the insights themselves, so an
    insight can never come back without its alerts. Rows go one at a time rather than through a
    queryset delete, because a queryset delete never calls ``AlertConfiguration.delete()``, and
    ModelActivityMixin hangs its per-row activity logging off that override.
    """
    # Caller-supplied ids that are already team-scoped by the caller's own query.
    # nosemgrep: idor-lookup-without-team
    for alert in AlertConfiguration.objects.filter(insight_id__in=insight_ids):
        alert.delete()


def serialize_insight_alerts(alerts: Collection[AlertConfiguration], context: dict[str, Any]) -> list[dict[str, Any]]:
    """Render an insight's alerts for the insight API response.

    The insight API prefetches the alerts so the render costs no extra query, then hands them
    back here — the alert JSON shape is this product's to define, not product_analytics'.
    ``context`` is the calling serializer's DRF context.
    """
    # Deferred so the facade does not pull DRF onto its import path.
    from products.alerts.backend.presentation.views.alert import AlertSerializer  # noqa: PLC0415

    # `many=True` yields a ReturnList; the DRF stubs type `.data` as ReturnDict either way.
    return cast(list[dict[str, Any]], AlertSerializer(alerts, many=True, context=context).data)


def snooze_alert_from_slack(
    alert_id: uuid.UUID, *, user: User, duration: str | None = None, until: datetime | None = None
) -> SlackSnoozeOutcome:
    """Snooze an alert on behalf of a Slack snooze interaction.

    Takes exactly one of ``duration`` (a preset token like ``"1d"``, resolved with the same
    ``relative_date_parse`` call the alerts API uses) or ``until`` (an absolute time from
    Slack's datetimepicker, which must be in the future and at most ``SLACK_SNOOZE_MAX_DAYS``
    out).

    Owns all alert-side authorization and the mutation itself. `user` must already be confirmed
    as a member of the alert's Slack-connected organization by the caller — the alert_id and
    duration come from an untrusted Slack button value (user-editable hog function config), so
    every access decision here is re-derived from the alert row, never taken on trust from the
    caller.
    """
    if (duration is None) == (until is None):
        raise ValueError("Pass exactly one of duration or until")
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
        # Fast path only — not the authoritative check. A concurrent disable between here and
        # the row-locked re-check below must still be caught, so this just avoids taking a lock
        # for the common case.
        return "disabled"

    if duration is not None:
        # always store snoozed_until as UTC time, as we look at current UTC time to check when to
        # run alerts — same call the alerts API uses so "1d" means the same thing everywhere.
        snoozed_until = relative_date_parse(duration, ZoneInfo("UTC"), increase=True, always_truncate=True)
    else:
        assert until is not None
        now = timezone.now()
        if until <= now or until > now + timedelta(days=SLACK_SNOOZE_MAX_DAYS):
            return "invalid_until"
        snoozed_until = until.astimezone(ZoneInfo("UTC"))

    with transaction.atomic():
        try:
            # Authoritative re-check under a row lock: without this, a concurrent disable
            # between the fast-path check above and this mutation would still persist
            # enabled=False alongside state=SNOOZED — a state the alert should never be in.
            # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get
            locked_alert = AlertConfiguration.objects.select_for_update().get(id=alert_id)
        except AlertConfiguration.DoesNotExist:
            return "not_found"

        if not locked_alert.enabled:
            return "disabled"

        with ActingUserContext(user):
            state_fields = apply_snooze(locked_alert)
            locked_alert.snoozed_until = snoozed_until
            locked_alert.save(update_fields=[*state_fields, "snoozed_until"])
            AlertCheck.objects.create(
                alert_configuration=locked_alert,
                calculated_value=None,
                condition=locked_alert.condition,
                targets_notified={},
                state=locked_alert.state,
                error=None,
            )

    return "snoozed"


__all__ = [
    "DESTINATION_TEMPLATE_IDS",
    "AlertDestinationData",
    "AlertDestinationValidationError",
    "AlertScheduleRestriction",
    "DestinationType",
    "SLACK_SNOOZE_MAX_DAYS",
    "SlackSnoozeOutcome",
    "build_alert_destination_config",
    "create_alert_destination_hog_functions",
    "delete_insight_alerts",
    "get_alert_team_id",
    "insight_alerts_prefetch",
    "insight_ids_with_alerts",
    "serialize_insight_alerts",
    "snooze_alert_from_slack",
    "soft_delete_alert_destinations",
    "soft_delete_alert_destinations_for_alerts",
    "soft_delete_all_alert_destinations",
    "send_alert_email",
    "validate_destination_data",
    "validate_and_normalize_schedule_restriction",
]
