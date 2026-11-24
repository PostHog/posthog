import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    GroupOutcome,
    InstanceCheckState,
    PlatformAlertCheckInput,
)
from products.alerts_platform.backend.facade.enums import OnMissingData, PlatformAlertState
from products.alerts_platform.backend.facade.grouping import (
    GroupObservation,
    bounded_grouping_key,
    decide_groups,
    is_hashed_grouping_key,
    not_breaching,
)
from products.alerts_platform.backend.facade.lifecycle import LOGS_ALERT_POLICY, AlertSnapshot, AlertState

_LONG = "x" * 300
_LONG_DIGEST = f"sha256:{hashlib.sha256(_LONG.encode()).hexdigest()}"


@pytest.mark.parametrize(
    "key, kept",
    [
        ("Chrome", True),
        ('{"service_name":"api"}', True),
        ("x" * 255, True),
        (_LONG, False),
        (_LONG_DIGEST, False),
        ("sha256:", False),
        ("Chr\x00me", False),
        ("Chr\ud800me", False),
    ],
    ids=["plain", "json", "at_limit", "too_long", "literal_digest", "literal_prefix", "nul", "lone_surrogate"],
)
def test_a_key_is_kept_only_when_the_column_can_store_it_and_it_cannot_read_as_a_hash(key: str, kept: bool) -> None:
    bounded = bounded_grouping_key(key)

    assert (bounded == key) is kept
    assert is_hashed_grouping_key(bounded) is not kept
    assert len(bounded) <= 255 and "\x00" not in bounded
    bounded.encode()


def test_a_literal_digest_does_not_share_a_row_with_the_long_key_it_spells() -> None:
    assert bounded_grouping_key(_LONG) == _LONG_DIGEST
    assert bounded_grouping_key(_LONG_DIGEST) != _LONG_DIGEST


_NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
_FIRING = InstanceCheckState(grouping_key="", state=PlatformAlertState.FIRING.value, firing_started_at=_NOW)
_RESTING = InstanceCheckState(grouping_key="", state=PlatformAlertState.NOT_FIRING.value)


def _check(
    on_missing_data: OnMissingData,
    *,
    instances: tuple[InstanceCheckState, ...] = (),
    evaluation_periods: int = 1,
    datapoints_to_alarm: int = 1,
) -> PlatformAlertCheckInput:
    return PlatformAlertCheckInput(
        id=uuid4(),
        team_id=1,
        name="Heartbeat",
        source_config={},
        check_interval_minutes=1,
        evaluation_periods=evaluation_periods,
        datapoints_to_alarm=datapoints_to_alarm,
        cooldown_minutes=0,
        schedule_restriction=None,
        next_check_at=None,
        consecutive_failures=0,
        legacy_configuration_id=None,
        check_status="ok",
        snooze_until=None,
        instances=instances,
        on_missing_data=on_missing_data,
    )


def _decided(
    check: PlatformAlertCheckInput, absent: Callable[[str], GroupObservation | None] = not_breaching
) -> dict[str, GroupOutcome]:
    decision = decide_groups(
        check,
        [],
        snapshot_of=lambda instance, prior: AlertSnapshot(
            state=AlertState(instance.state),
            cooldown=timedelta(0),
            last_notified_at=instance.last_notified_at,
            snooze_until=None,
            consecutive_failures=0,
            evaluation_periods=check.evaluation_periods,
            datapoints_to_alarm=check.datapoints_to_alarm,
            recent_events_breached=prior,
            firing_started_at=instance.firing_started_at,
        ),
        policy=LOGS_ALERT_POLICY,
        now=_NOW,
        absent=absent,
    )
    return {verdict.group.grouping_key: verdict.group for verdict in decision.verdicts}


@pytest.mark.parametrize(
    "on_missing_data, instances, expected",
    [
        (OnMissingData.RESOLVE, (_FIRING,), {"": (AlertEventKind.RESOLVED, "not_firing")}),
        (OnMissingData.KEEP_LAST_STATE, (_FIRING,), {}),
        (OnMissingData.BREACHING, (_FIRING,), {"": (AlertEventKind.CHECK, "firing")}),
        (OnMissingData.BREACHING, (), {"": (AlertEventKind.FIRING, "firing")}),
        (OnMissingData.RESOLVE, (), {}),
        (OnMissingData.NO_DATA, (_FIRING,), {"": (AlertEventKind.CHECK, "no_data")}),
        (OnMissingData.NOTIFY_NO_DATA, (_FIRING,), {"": (AlertEventKind.NO_DATA, "no_data")}),
        (OnMissingData.NOTIFY_NO_DATA, (_RESTING,), {"": (AlertEventKind.NO_DATA, "no_data")}),
        (OnMissingData.NOTIFY_NO_DATA, (), {"": (AlertEventKind.NO_DATA, "no_data")}),
        (OnMissingData.RESOLVE, (_RESTING,), {}),
    ],
    ids=[
        "resolve",
        "keep_last_state",
        "breaching_stays_firing",
        "breaching_fires_on_empty_result",
        "resolve_no_group",
        "no_data",
        "notify_no_data",
        "notify_no_data_from_healthy",
        "notify_no_data_on_empty_result",
        "resolve_leaves_healthy_alone",
    ],
)
def test_a_group_the_source_is_sure_is_missing_is_judged_by_the_alerts_choice(
    on_missing_data: OnMissingData,
    instances: tuple[InstanceCheckState, ...],
    expected: dict[str, tuple[AlertEventKind, str]],
) -> None:
    decided = _decided(_check(on_missing_data, instances=instances))

    assert {key: (group.kind, group.new_state) for key, group in decided.items()} == expected


@pytest.mark.parametrize("on_missing_data", list(OnMissingData))
def test_a_group_the_source_cannot_judge_yet_holds_whatever_the_alerts_choice(on_missing_data: OnMissingData) -> None:
    assert _decided(_check(on_missing_data, instances=(_FIRING,)), absent=lambda key: None) == {}


_HEALTHY = (False, False, False, False)


@pytest.mark.parametrize(
    "current, prior_missing, fires",
    [
        (None, (True, True, True, True), True),
        (None, (True, False, False, False), False),
        (None, (True, True, False, False), True),
        (None, _HEALTHY, False),
        (True, (True, True, True, True), True),
        (False, (True, True, False, False), False),
    ],
    ids=[
        "missing_for_the_whole_window",
        "first_missing_check",
        "third_missing_check",
        "healthy_history",
        "back_and_breaching",
        "back_and_clear_after_two_missing",
    ],
)
def test_breaching_counts_every_earlier_missing_check_toward_n_of_m(
    current: bool | None, prior_missing: tuple[bool, ...], fires: bool
) -> None:
    check = _check(OnMissingData.BREACHING, evaluation_periods=5, datapoints_to_alarm=3)
    observed = GroupObservation(
        grouping_key="", current_breached=bool(current), prior_breached=_HEALTHY, prior_missing=prior_missing
    )
    decision = decide_groups(
        check,
        [] if current is None else [observed],
        snapshot_of=lambda instance, prior: AlertSnapshot(
            state=AlertState(instance.state),
            cooldown=timedelta(0),
            last_notified_at=None,
            snooze_until=None,
            consecutive_failures=0,
            evaluation_periods=5,
            datapoints_to_alarm=3,
            recent_events_breached=prior,
        ),
        policy=LOGS_ALERT_POLICY,
        now=_NOW,
        absent=lambda key: observed,
    )

    assert [verdict.group.new_state for verdict in decision.verdicts] == (["firing"] if fires else [])
