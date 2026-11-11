"""Facade for insight alerts.

Reads and writes other products need on the insight-alert model, in ids and plain values.
Destination configuration lives in `facade.destinations`, email in `facade.email`, the
lifecycle machine in `facade.lifecycle`, and scheduling math in `facade.scheduling`.
"""

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from itertools import islice
from typing import Literal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import ActingUserContext
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_enums import AlertState
from posthog.user_permissions import UserPermissions
from posthog.utils import relative_date_parse

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend import platform_subscribers
from products.alerts.backend.activity_logging import AlertConfigurationContext
from products.alerts.backend.facade import contracts
from products.alerts.backend.insight_alert_state_machine import apply_snooze
from products.alerts.backend.judge.contract import (
    LLM_DETECTOR_PAUSED_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_ERROR_CODE,
    LLM_DETECTOR_UNAVAILABLE_MESSAGE,
    MAX_CONCURRENT_MODEL_CALLS,
    MAX_PROMPT_POINTS,
    LLMDetectorError,
    LLMDetectorMisconfiguredError,
    LLMDetectorPausedError,
    LLMDetectorUnavailableError,
)
from products.alerts.backend.judge.executor import LLM_EVALUATE_EXECUTOR
from products.alerts.backend.llm_detector_limits import (
    LLMAlertRefusal,
    LLMAlertWrite,
    admit_llm_alert_write,
    is_llm_detector_config,
    llm_detector_access_error,
)
from products.alerts.backend.logic.destinations import retire_alert_hog_functions
from products.alerts.backend.models.alert import (
    METRICS_INSIGHT_QUERY_FILTER,
    AlertCheck,
    AlertConfiguration,
    AlertSubscription,
)
from products.alerts.backend.platform_insight_alert import native_insight_alert_view
from products.alerts_platform.backend.facade.api import (
    assign_native_creator,
    enabled_native_configurations,
    native_configuration_team_id,
    update_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    EnabledNativeConfiguration,
    InvalidPlatformAlertEdit,
    SourceKind,
)
from products.product_analytics.backend.facade.api import insights_including_soft_deleted_for_team
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)

SlackSnoozeOutcome = Literal["snoozed", "no_access", "disabled", "not_found", "invalid_until", "not_snoozable"]

# Mirrors the in-app SnoozeButton's DateFilter max — Slack's datetimepicker has no bounds of
# its own, so the cap has to live here.
SLACK_SNOOZE_MAX_DAYS = 31


def first_subscriber_id(*, team_id: int, alert_id: uuid.UUID) -> int | None:
    """One of the alert's subscribers, for a chart render or an investigation to run as. None when nobody subscribes."""
    return platform_subscribers.first_subscriber_id(team_id=team_id, alert_id=alert_id)


def remove_member_subscriptions(*, user_id: int, organization_id: uuid.UUID) -> int:
    """Unsubscribes a user who left an organization from its insight alerts, on the platform's copies
    too, and returns how many subscriptions they had."""
    return platform_subscribers.remove_member_subscriptions(user_id=user_id, organization_id=organization_id)


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
    team_id = AlertConfiguration.objects.filter(id=alert_id).values_list("team_id", flat=True).first()
    if team_id is not None:
        return team_id
    # An alert with no insight row carries its platform alert's id.
    return native_configuration_team_id(configuration_id=alert_id, source_kind=SourceKind.INSIGHT)


def insight_ids_with_alerts(insight_ids: Collection[int]) -> set[int]:
    """Which of the given insights have at least one alert configured.

    Lets callers outside this product treat "an alert points at this insight" as a signal that
    something depends on it, without importing the model.
    """
    # Caller-supplied ids that are already team-scoped by the caller's own query; this only maps
    # ids to ids and returns no row data.
    # nosemgrep: idor-lookup-without-team
    return set(AlertConfiguration.objects.filter(insight_id__in=insight_ids).values_list("insight_id", flat=True))


def insight_ids_with_enabled_alerts(*, team_id: int, insight_ids: Collection[int]) -> set[int]:
    """Which of the team's given insights have at least one enabled alert, in one query."""
    wanted = set(insight_ids)
    return set(
        AlertConfiguration.objects.filter(team_id=team_id, insight_id__in=insight_ids, enabled=True).values_list(
            "insight_id", flat=True
        )
    ) | _native_enabled_insight_ids(team_ids=[team_id], insight_ids=wanted)


def enabled_alert_insight_ids(*, team_ids: Collection[int]) -> set[int]:
    """Insights of these teams with at least one enabled alert, in one query."""
    if not team_ids:
        return set()
    return set(
        AlertConfiguration.objects.filter(team_id__in=team_ids, enabled=True)
        .values_list("insight_id", flat=True)
        .distinct()
    ) | _native_enabled_insight_ids(team_ids=team_ids)


def _native_enabled_insight_ids(*, team_ids: Collection[int], insight_ids: Collection[int] | None = None) -> set[int]:
    return {
        insight_id
        for configuration in enabled_native_configurations(
            team_ids=team_ids,
            source_kind=SourceKind.INSIGHT,
            source_config_key=None if insight_ids is None else "insight_id",
            values=() if insight_ids is None else insight_ids,
        )
        if isinstance(insight_id := configuration.source_config.get("insight_id"), int)
    }


def delete_insight_alerts(insight_ids: Collection[int]) -> None:
    """Delete the alerts pointing at the given insights.

    Call this inside the transaction that deletes or hides the insights themselves, so an
    insight can never come back without its alerts. Rows go one at a time rather than through a
    queryset delete, because a queryset delete never calls ``AlertConfiguration.delete()``, and
    ModelActivityMixin hangs its per-row activity logging off that override.

    The platform's alerts, with an insight row or without one, lose their copies and destinations in
    a workflow started after the transaction commits, because the platform resolves their open
    incidents first, which calls the providers, and a rollback cannot take a resolve back. The
    workflow retries each delete. An alert insight owns loses its destinations here.
    """
    # The alert rows are locked, in id order, before any destination is saved. The alert API's delete
    # locks the alert before its destinations too, so the two cannot deadlock on one alert.
    with transaction.atomic():
        # Caller-supplied ids that are already team-scoped by the caller's own query.
        # nosemgrep: idor-lookup-without-team
        alerts = list(
            AlertConfiguration.objects.select_for_update(of=("self",)).filter(insight_id__in=insight_ids).order_by("id")
        )
        for alert in alerts:
            if not alert.platform_owned:
                retire_alert_hog_functions(team_id=alert.team_id, alert_id=str(alert.id))
            alert.delete()
    # nosemgrep: idor-lookup-without-team
    insights_by_team: dict[int, list[int]] = {}
    for team_id, insight_id in Insight.objects_including_soft_deleted.filter(id__in=insight_ids).values_list(
        "team_id", "id"
    ):
        insights_by_team.setdefault(team_id, []).append(insight_id)
    transaction.on_commit(lambda: _start_native_cleanup(insights_by_team))


def _start_native_cleanup(insights_by_team: dict[int, list[int]]) -> None:
    # Deferred, so the Temporal client stays off this facade's import graph.
    from products.alerts.backend.platform_native_cleanup import start_native_cleanup  # noqa: PLC0415

    start_native_cleanup(insights_by_team)


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
        return _snooze_native_from_slack(alert_id, user=user, duration=duration, until=until)

    if not _can_snooze_from_slack(alert, user=user):
        return "no_access"

    if not alert.enabled:
        # Fast path only — not the authoritative check. A concurrent disable between here and
        # the row-locked re-check below must still be caught, so this just avoids taking a lock
        # for the common case.
        return "disabled"

    snoozed_until = _slack_snoozed_until(duration=duration, until=until)
    if snoozed_until is None:
        return "invalid_until"

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
            if locked_alert.platform_owned:
                # The platform's copy mutes delivery, so it takes the snooze under the same lock.
                from products.alerts.backend.platform_ownership import (  # noqa: PLC0415 - platform_ownership reaches this module back
                    on_updated,
                )

                try:
                    on_updated(locked_alert, snooze_changed=True)
                except (contracts.PlatformCannotOwn, InvalidPlatformAlertEdit) as error:
                    # Neither row takes the snooze, so the alert does not mute on one stack only.
                    capture_exception(error, {"alert_id": str(alert_id)})
                    transaction.set_rollback(True)
                    return "not_snoozable"
            AlertCheck.objects.create(
                alert_configuration=locked_alert,
                calculated_value=None,
                condition=locked_alert.condition,
                targets_notified={},
                state=locked_alert.state,
                error=None,
            )

    return "snoozed"


def _can_snooze_from_slack(alert: AlertConfiguration, *, user: User) -> bool:
    # Mirrors TeamMemberAccessPermission (posthog/permissions.py): a non-admin member with no
    # explicit membership in a private project must be denied, even though they belong to the
    # organization. effective_membership_level falls back to the plain org membership level when
    # the organization doesn't have ACCESS_CONTROL, so this never false-denies on non-EE orgs.
    if UserPermissions(user).team(alert.team).effective_membership_level is None:
        logger.warning("alert_snooze_no_project_membership", alert_id=str(alert.id), user_id=user.id)
        return False

    # Project membership doesn't imply access to every insight in it — mirrors
    # _require_insight_viewer_access, the same check the alerts API itself uses.
    if not UserAccessControl(user, team=alert.team).check_access_level_for_object(alert.insight, "viewer"):
        logger.warning("alert_snooze_no_insight_access", alert_id=str(alert.id), user_id=user.id)
        return False
    return True


def _slack_snoozed_until(*, duration: str | None, until: datetime | None) -> datetime | None:
    """When a Slack snooze ends, in UTC, or None for an `until` outside the allowed window."""
    if duration is not None:
        # always store snoozed_until as UTC time, as we look at current UTC time to check when to
        # run alerts — same call the alerts API uses so "1d" means the same thing everywhere.
        return relative_date_parse(duration, ZoneInfo("UTC"), increase=True, always_truncate=True)
    assert until is not None
    now = timezone.now()
    if until <= now or until > now + timedelta(days=SLACK_SNOOZE_MAX_DAYS):
        return None
    return until.astimezone(ZoneInfo("UTC"))


def _snooze_native_from_slack(
    alert_id: uuid.UUID, *, user: User, duration: str | None, until: datetime | None
) -> SlackSnoozeOutcome:
    """`snooze_alert_from_slack` for an insight alert with no insight row, whose snooze the platform keeps."""
    team_id = native_configuration_team_id(configuration_id=alert_id, source_kind=SourceKind.INSIGHT)
    if team_id is None:
        return "not_found"
    try:
        alert = _native_alert(team_id=team_id, alert_id=alert_id)
    except AlertConfiguration.DoesNotExist:
        return "not_found"
    if not _can_snooze_from_slack(alert, user=user):
        return "no_access"
    if not alert.enabled:
        return "disabled"
    snoozed_until = _slack_snoozed_until(duration=duration, until=until)
    if snoozed_until is None:
        return "invalid_until"
    with transaction.atomic(), ActingUserContext(user):
        # Rechecked under the platform's lock, so a concurrent disable never ends up snoozed.
        view = native_insight_alert_view(team_id, alert_id, lock=True)
        if view is None:
            return "not_found"
        if not view.enabled:
            return "disabled"
        try:
            snoozed = update_configuration(
                team_id=team_id,
                source_kinds=[SourceKind.INSIGHT.value],
                configuration_id=alert_id,
                change=lambda stored: stored,
                snooze_until=snoozed_until,
                snooze_changed=True,
                # A snooze changes no setting the guard checks.
                source_checked=True,
            )
        except InvalidPlatformAlertEdit as error:
            capture_exception(error, {"alert_id": str(alert_id)})
            return "not_snoozable"
    return "snoozed" if snoozed is not None else "not_found"


FIRING_ALERT_CANDIDATES = 200


def list_firing_alerts_created_by(
    team: Team, user: User, *, include_metrics_insights: bool, limit: int
) -> list[contracts.FiringAlert]:
    alerts = AlertConfiguration.objects.filter(
        team_id=team.id,
        enabled=True,
        state=AlertState.FIRING,
        created_by_id=user.id,
        insight__deleted=False,
    ).filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=timezone.now()))
    if not include_metrics_insights:
        alerts = alerts.exclude(id__in=alerts.filter(METRICS_INSIGHT_QUERY_FILTER).values("id"))
    access = UserAccessControl(user, team=team)
    candidates = alerts.select_related("insight").order_by("-created_at")[:FIRING_ALERT_CANDIDATES]
    viewable = (alert for alert in candidates if access.check_access_level_for_object(alert.insight, "viewer"))
    return [
        contracts.FiringAlert(
            id=alert.id,
            name=alert.name,
            insight_name=alert.insight.name or alert.insight.derived_name,
            insight_short_id=alert.insight.short_id,
        )
        for alert in islice(viewable, limit)
    ]


ENABLED_ALERT_CANDIDATES = 500


def list_enabled_alerts(team: Team, user: User, *, limit: int) -> list[contracts.EnabledAlert]:
    """Enabled alerts on insights the user can view, newest first, with or without an insight row."""
    access = UserAccessControl(user, team=team)
    rows = (
        AlertConfiguration.objects.filter(team_id=team.id, enabled=True, insight__deleted=False)
        .select_related("insight")
        .order_by("-created_at")[:ENABLED_ALERT_CANDIDATES]
    )
    candidates = sorted(
        [
            *(
                _EnabledCandidate(created_at=alert.created_at, id=alert.id, name=alert.name, insight=alert.insight)
                for alert in rows
            ),
            *(
                _EnabledCandidate(
                    created_at=configuration.created_at, id=configuration.id, name=configuration.name, insight=insight
                )
                for configuration, insight in _native_enabled_alerts(team_id=team.id, limit=ENABLED_ALERT_CANDIDATES)
            ),
        ],
        key=lambda candidate: candidate.created_at,
        reverse=True,
    )[:ENABLED_ALERT_CANDIDATES]
    viewable = (
        candidate for candidate in candidates if access.check_access_level_for_object(candidate.insight, "viewer")
    )
    return [
        contracts.EnabledAlert(
            id=candidate.id,
            name=candidate.name,
            insight_name=candidate.insight.name or candidate.insight.derived_name,
            insight_short_id=candidate.insight.short_id,
        )
        for candidate in islice(viewable, limit)
    ]


@frozen
class _EnabledCandidate:
    created_at: datetime
    id: uuid.UUID
    name: str
    insight: Insight


def _native_enabled_alerts(
    *, team_id: int, limit: int, created_by_id: int | None = None
) -> list[tuple[EnabledNativeConfiguration, Insight]]:
    """The team's newest `limit` enabled insight alerts with no insight row, newest first, each with its
    insight. An alert whose insight is gone or deleted is left out, as a row's is."""
    configurations = enabled_native_configurations(
        team_ids=[team_id], source_kind=SourceKind.INSIGHT, created_by_id=created_by_id, limit=limit
    )
    insight_ids = {
        insight_id
        for configuration in configurations
        if isinstance(insight_id := configuration.source_config.get("insight_id"), int)
    }
    insights = {
        insight.id: insight
        for insight in insights_including_soft_deleted_for_team(team_id=team_id, insight_ids=insight_ids)
        if not insight.deleted
    }
    return [
        (configuration, insights[insight_id])
        for configuration in configurations
        if (insight_id := configuration.source_config.get("insight_id")) in insights
    ]


WATCHED_ROWS_PER_INSIGHT = 4


def insight_short_ids_watched_by(*, team_id: int, user_id: int, limit: int) -> list[str]:
    """Short ids of insights with an enabled alert that the user created or subscribes to, newest alert first.
    An alert with no insight row has no subscribers, so only its creator watches it."""
    follows = AlertSubscription.objects.filter(alert_configuration=OuterRef("pk"), user_id=user_id, subscribed=True)
    rows = (
        AlertConfiguration.objects.filter(team_id=team_id, enabled=True, insight__deleted=False)
        .filter(Q(created_by_id=user_id) | Exists(follows))
        .order_by("-created_at")
        .values_list("created_at", "insight__short_id")[: limit * WATCHED_ROWS_PER_INSIGHT]
    )
    native = [
        (configuration.created_at, insight.short_id)
        for configuration, insight in _native_enabled_alerts(
            team_id=team_id, created_by_id=user_id, limit=limit * WATCHED_ROWS_PER_INSIGHT
        )
    ]
    newest_first = sorted([*rows, *native], key=lambda row: row[0], reverse=True)
    return list(dict.fromkeys(short_id for _, short_id in newest_first))[:limit]


def assign_alert_owner(*, team_id: int, alert_id: uuid.UUID, user: User, was_impersonated: bool) -> None:
    """Make `user` the owner of the alert and record the takeover in the activity log.

    `created_by` is excluded from the save diff, so the takeover gets its own activity. An alert with
    no insight row is the platform's, which stores its creator.
    """
    alert = (
        AlertConfiguration.objects.select_related("insight", "created_by").filter(team_id=team_id, id=alert_id).first()
    )
    if alert is not None:
        previous_owner = alert.created_by
        alert.created_by = user
        alert.save(update_fields=["created_by"])
    else:
        alert = _native_alert(team_id=team_id, alert_id=alert_id)
        previous_owner = alert.created_by
        _assign_native_creator(team_id=team_id, alert_id=alert_id, user=user)
    log_activity(
        organization_id=alert.team.organization_id,
        team_id=alert.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=alert.id,
        scope="AlertConfiguration",
        activity="took_ownership",
        detail=Detail(
            name=alert.name or f"Alert for {alert.insight.name}",
            changes=[
                Change(
                    type="AlertConfiguration",
                    action="changed",
                    field="created_by",
                    before={"id": previous_owner.id, "email": previous_owner.email} if previous_owner else None,
                    after={"id": user.id, "email": user.email},
                )
            ],
            context=AlertConfigurationContext(
                insight_id=alert.insight_id,
                insight_short_id=alert.insight.short_id,
                insight_name=alert.insight.name,
            ),
        ),
    )


def _native_alert(*, team_id: int, alert_id: uuid.UUID) -> AlertConfiguration:
    """The insight alert with no insight row under `alert_id`, as the API presents it. Raises
    `AlertConfiguration.DoesNotExist`, as a missing row does."""
    view = native_insight_alert_view(team_id, alert_id)
    alert = AlertConfiguration.from_platform_view(view, team_id=team_id) if view is not None else None
    if alert is None:
        raise AlertConfiguration.DoesNotExist(f"No insight alert {alert_id} in team {team_id}")
    return alert


def _assign_native_creator(*, team_id: int, alert_id: uuid.UUID, user: User) -> None:
    if not assign_native_creator(
        team_id=team_id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=alert_id, created_by_id=user.id
    ):
        raise AlertConfiguration.DoesNotExist(f"No insight alert {alert_id} in team {team_id}")


__all__ = [
    "LLM_DETECTOR_PAUSED_ERROR_CODE",
    "LLM_DETECTOR_UNAVAILABLE_ERROR_CODE",
    "LLM_DETECTOR_UNAVAILABLE_MESSAGE",
    "LLM_EVALUATE_EXECUTOR",
    "MAX_CONCURRENT_MODEL_CALLS",
    "MAX_PROMPT_POINTS",
    "LLMAlertRefusal",
    "LLMAlertWrite",
    "LLMDetectorError",
    "LLMDetectorMisconfiguredError",
    "LLMDetectorPausedError",
    "LLMDetectorUnavailableError",
    "admit_llm_alert_write",
    "assign_alert_owner",
    "is_llm_detector_config",
    "llm_detector_access_error",
]
