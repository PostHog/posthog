"""The insight alert a platform alert stands for: its insight row for a copy, or one built from the
platform alert's settings when insight keeps no row for it."""

from collections.abc import Collection
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from django.db.models import Prefetch, prefetch_related_objects

from posthog.models.tagged_item import TaggedItem
from posthog.models.team import Team
from posthog.models.user import User
from posthog.schema_enums import AlertCalculationInterval, InsightThresholdType

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.alerts.backend.models.alert import AlertConfiguration, Threshold
from products.alerts_platform.backend.facade.api import (
    delete_owned_configuration,
    get_configuration,
    list_configurations,
    native_configuration_matches,
    update_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    NativeConfigurationMatch,
    PlatformAlertCheckInput,
    PlatformAlertConfigurationView,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import (
    PlatformAlertConfigurationRecurrenceUnit as RecurrenceUnit,
    PlatformAlertOwner,
)
from products.alerts_platform.backend.facade.scheduling import REAL_TIME_CADENCE_MINUTES
from products.product_analytics.backend.facade.api import insights_including_soft_deleted_for_team
from products.product_analytics.backend.facade.models import Insight

# Minutes for the real-time, 15-minute and hourly cadences, a calendar unit for the rest. A calendar
# unit reads its cadence from the unit, so its minutes only feed the shard offset, which an anchored
# unit ignores.
RECURRENCE: Final[dict[str, tuple[int, str | None]]] = {
    AlertCalculationInterval.REAL_TIME: (REAL_TIME_CADENCE_MINUTES, None),
    AlertCalculationInterval.EVERY_15_MINUTES: (15, None),
    AlertCalculationInterval.HOURLY: (60, None),
    AlertCalculationInterval.DAILY: (60 * 24, RecurrenceUnit.DAY),
    AlertCalculationInterval.WEEKLY: (60 * 24 * 7, RecurrenceUnit.WEEK),
    AlertCalculationInterval.MONTHLY: (60 * 24 * 30, RecurrenceUnit.MONTH),
}


# Settings only the insight API may change, because it checks them against the insight's query or
# against its project's model spend. An edit through the platform API keeps their stored values.
INSIGHT_ROW_SETTINGS: Final = frozenset(
    {
        "config",
        "skip_weekend",
        "evaluation_delay_intervals",
        "investigation_agent_enabled",
        "investigation_gates_notifications",
        "investigation_inconclusive_action",
    }
)


def insight_row_settings(alert: AlertConfiguration) -> dict[str, Any]:
    """The `INSIGHT_ROW_SETTINGS` of an insight row, as its platform copy stores them."""
    return {
        "config": alert.config,
        "skip_weekend": bool(alert.skip_weekend),
        "evaluation_delay_intervals": alert.evaluation_delay_intervals,
        "investigation_agent_enabled": alert.investigation_agent_enabled,
        "investigation_gates_notifications": alert.investigation_gates_notifications,
        "investigation_inconclusive_action": alert.investigation_inconclusive_action,
    }


def interval_of(check_interval_minutes: int) -> str | None:
    """The insight cadence a platform alert's `check_interval_minutes` stands for, or None for one insight has not."""
    return next((interval for interval, (minutes, _) in RECURRENCE.items() if minutes == check_interval_minutes), None)


def insight_of(team_id: int, source_config: dict) -> Insight | None:
    """The insight a platform alert reads, or None when it is gone or deleted."""
    insight_id = source_config.get("insight_id")
    if not isinstance(insight_id, int):
        return None
    found = insights_including_soft_deleted_for_team(team_id=team_id, insight_ids=[insight_id])
    return found[0] if found and not found[0].deleted else None


def subscribers_with_insight_access(*, team_id: int, configuration_id: UUID, user_ids: Collection[int]) -> list[int]:
    """The users who can still view the insight an insight alert watches. Nobody, once it is gone."""
    configuration = get_configuration(
        team_id=team_id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=configuration_id
    )
    insight = insight_of(team_id, configuration.source_config) if configuration is not None else None
    if insight is None:
        return []
    controls = UserAccessControl.for_user_ids(user_ids=user_ids, team=Team.objects.get(id=team_id))
    return [
        user_id for user_id, control in controls.items() if control.check_access_level_for_object(insight, "viewer")
    ]


def evaluation_alert(check: PlatformAlertCheckInput) -> AlertConfiguration | None:
    """The alert a check evaluates: a copy's insight row, or, for an alert insight keeps no row for,
    one built from the platform alert. None when either is gone."""
    if check.legacy_configuration_id is None:
        return alert_from_platform(check, team_id=check.team_id, enabled=True)
    return legacy_alert(team_id=check.team_id, alert_id=check.legacy_configuration_id)


def investigated_alert(team_id: int, alert_id: UUID) -> AlertConfiguration | None:
    """The alert an investigation names: its insight row, or, for an alert insight keeps no row for,
    one built from the platform alert, whose id it carries. None when both are gone."""
    if (alert := legacy_alert(team_id=team_id, alert_id=alert_id)) is not None:
        return alert
    configuration = get_configuration(
        team_id=team_id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=alert_id
    )
    if configuration is None or configuration.legacy_configuration_id is not None:
        return None
    return alert_from_platform(configuration, team_id=team_id, enabled=configuration.enabled)


def native_insight_alert_view(
    team_id: int, alert_id: UUID, *, lock: bool = False
) -> PlatformAlertConfigurationView | None:
    """The team's insight alert with no insight row under `alert_id`, as the platform keeps it, or None.
    With `lock`, its row stays locked until the caller's transaction ends."""
    configuration = get_configuration(
        team_id=team_id, source_kinds=[SourceKind.INSIGHT.value], configuration_id=alert_id, lock=lock
    )
    return configuration if configuration is not None and configuration.legacy_configuration_id is None else None


def enable_native_insight_alert(*, team_id: int, alert_id: UUID) -> PlatformAlertConfigurationView | None:
    """Turns on an insight alert with no insight row, through the platform's admission, once the
    insight API has run its own checks. None when it is gone.

    Raises `InvalidPlatformAlertEdit` when the admission refuses it.
    """
    return update_configuration(
        team_id=team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        configuration_id=alert_id,
        change=lambda stored: replace(stored, enabled=True),
        source_checked=True,
    )


def delete_native_insight_alert(*, team_id: int, alert_id: UUID) -> None:
    """Deletes an insight alert with no insight row: sends the resolves of its open firings while its
    destinations still exist, then removes them and the alert. Call it outside any transaction."""
    delete_owned_configuration(team_id=team_id, configuration_id=alert_id)


def native_insight_alert_matches(team_id: int, *, search: str | None) -> tuple[NativeConfigurationMatch, ...]:
    """Every insight alert with no insight row, or with `search` the ones whose name matches it."""
    return native_configuration_matches(team_id=team_id, source_kind=SourceKind.INSIGHT, search=search)


def native_insight_alert_views(team_id: int, alert_ids: Collection[UUID]) -> tuple[PlatformAlertConfigurationView, ...]:
    """The named insight alerts with no insight row, as the platform keeps them, in no particular order."""
    if not alert_ids:
        return ()
    page = list_configurations(
        team_id=team_id,
        source_kinds=[SourceKind.INSIGHT.value],
        limit=len(alert_ids),
        offset=0,
        configuration_ids=alert_ids,
    )
    return tuple(
        configuration for configuration in page.configurations if configuration.legacy_configuration_id is None
    )


def presented_alert(configuration: PlatformAlertConfigurationView, *, team_id: int) -> AlertConfiguration | None:
    """An unsaved alert that presents an insight alert with no insight row the way the API shows a
    row. Its `save` and `delete` raise, because every write goes to the platform. None when its
    insight is gone."""
    alert = alert_from_platform(configuration, team_id=team_id, enabled=configuration.enabled)
    return _presented(alert, configuration) if alert is not None else None


def presented_alerts(
    configurations: Collection[PlatformAlertConfigurationView], *, team_id: int
) -> dict[UUID, AlertConfiguration]:
    """`presented_alert` for a page of alerts, keyed by id, loading their insights and creators in
    one query each. An alert whose insight is gone is left out."""
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
    prefetch_related_objects(
        list(insights.values()),
        "team__organization",
        # Where the alert serializer reads an insight's tags, as the viewset prefetches them for rows.
        Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags"),
    )
    creator_ids = {configuration.created_by_id for configuration in configurations} - {None}
    creators = {user.id: user for user in User.objects.filter(id__in=creator_ids)}
    presented: dict[UUID, AlertConfiguration] = {}
    for configuration in configurations:
        insight_id = configuration.source_config.get("insight_id")
        insight = insights.get(insight_id) if isinstance(insight_id, int) else None
        if insight is None:
            continue
        alert = _built_alert(
            configuration,
            insight=insight,
            created_by=creators.get(configuration.created_by_id) if configuration.created_by_id is not None else None,
            enabled=configuration.enabled,
        )
        presented[configuration.id] = _presented(alert, configuration)
    return presented


def _presented(alert: AlertConfiguration, configuration: PlatformAlertConfigurationView) -> AlertConfiguration:
    alert.created_at = configuration.created_at
    # The platform checked the alert from its creation, so its whole history is the platform's.
    alert.owner_changed_at = configuration.created_at
    # The schedule's minute, which a row keeps as its start time and the platform as its anchor.
    alert.schedule_start_time = configuration.anchor_time
    if alert.threshold is None:
        # Every insight row has a threshold, and the API's readers expect one.
        alert.threshold = Threshold(
            team=alert.team, insight=alert.insight, configuration={"type": InsightThresholdType.ABSOLUTE.value}
        )
    # An unsaved threshold has no `created_at`, which the API's readers expect, and a fresh id on
    # every read. The alert's id keeps the threshold's id the same from one read to the next.
    alert.threshold.created_at = configuration.created_at
    alert.threshold.id = configuration.id
    # What the viewset annotates on a row. The platform's last check replaces it when there is one.
    alert.last_value = None  # type: ignore[attr-defined]
    # An alert with no insight row has no subscriptions. Cached as the viewset prefetches them for
    # rows, so the serializer does not query for each alert.
    alert._prefetched_objects_cache = {"subscribed_users": User.objects.none()}  # type: ignore[attr-defined]
    for method in ("save", "delete"):
        setattr(alert, method, _no_insight_row)
    return alert


def _no_insight_row(*args: object, **kwargs: object) -> None:
    raise TypeError("This insight alert has no insight row. Write it through the platform.")


def is_built_from_platform(alert: AlertConfiguration, configuration_id: UUID) -> bool:
    """Whether the alert has no insight row. A built alert carries its platform alert's id, and a
    copy's row never does."""
    return alert.id == configuration_id


def alert_from_platform(
    configuration: PlatformAlertCheckInput | PlatformAlertConfigurationView, *, team_id: int, enabled: bool
) -> AlertConfiguration | None:
    """An unsaved insight alert with the platform alert's settings, so the insight evaluation and
    its investigations run it unchanged. None when its insight is gone."""
    insight = insight_of(team_id, configuration.source_config)
    if insight is None:
        return None
    # Prefetched for the same reason as `legacy_alert`'s.
    prefetch_related_objects([insight], "team__organization", "tagged_items__tag")
    created_by_id = configuration.created_by_id
    created_by = User.objects.filter(id=created_by_id).first() if created_by_id is not None else None
    return _built_alert(configuration, insight=insight, created_by=created_by, enabled=enabled)


def _built_alert(
    configuration: PlatformAlertCheckInput | PlatformAlertConfigurationView,
    *,
    insight: Insight,
    created_by: User | None,
    enabled: bool,
) -> AlertConfiguration:
    source_config = configuration.source_config
    condition = source_config.get(SOURCE_CONDITION_KEY) or {}
    threshold_config = condition.get("threshold")
    return AlertConfiguration(
        id=configuration.id,
        team=insight.team,
        insight=insight,
        name=configuration.name,
        enabled=enabled,
        config=source_config.get("config") or {},
        condition=condition.get("comparison") or {},
        detector_config=condition.get("detector"),
        threshold=Threshold(team=insight.team, insight=insight, configuration=threshold_config)
        if threshold_config
        else None,
        calculation_interval=interval_of(configuration.check_interval_minutes),
        skip_weekend=source_config.get("skip_weekend", False),
        evaluation_delay_intervals=source_config.get("evaluation_delay_intervals", 0),
        investigation_agent_enabled=source_config.get("investigation_agent_enabled", False),
        investigation_gates_notifications=source_config.get("investigation_gates_notifications", False),
        investigation_inconclusive_action=source_config.get("investigation_inconclusive_action", "notify"),
        schedule_restriction=configuration.schedule_restriction,
        snoozed_until=configuration.snooze_until,
        owner=PlatformAlertOwner.PLATFORM,
        created_by=created_by,
    )


def legacy_alert(*, team_id: int, alert_id: UUID) -> AlertConfiguration | None:
    return (
        AlertConfiguration.objects.select_related("insight", "team", "threshold", "created_by")
        # A firing's card names the insight's tags. Prefetched with the alert, because a reverse
        # many-to-many cannot be selected, and the read would otherwise be its own round trip
        # inside the window the check holds its admission slot.
        .prefetch_related("insight__tagged_items__tag")
        .filter(team_id=team_id, id=alert_id)
        .first()
    )
