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
        (OnMissingData.RESOLVE, (_FIRING,), {"": (AlertEventKind.RESOLVED, "not_firing", True)}),
        (OnMissingData.KEEP_LAST_STATE, (_FIRING,), {}),
        (OnMissingData.BREACHING, (_FIRING,), {"": (AlertEventKind.CHECK, "firing", False)}),
        (OnMissingData.BREACHING, (), {"": (AlertEventKind.FIRING, "firing", False)}),
        (OnMissingData.RESOLVE, (), {}),
        (OnMissingData.NO_DATA, (_FIRING,), {"": (AlertEventKind.CHECK, "no_data", True)}),
        (OnMissingData.NOTIFY_NO_DATA, (_FIRING,), {"": (AlertEventKind.NO_DATA, "no_data", True)}),
        (OnMissingData.NOTIFY_NO_DATA, (_RESTING,), {"": (AlertEventKind.NO_DATA, "no_data", True)}),
        (OnMissingData.NOTIFY_NO_DATA, (), {"": (AlertEventKind.NO_DATA, "no_data", True)}),
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
    expected: dict[str, tuple[AlertEventKind, str, bool]],
) -> None:
    decided = _decided(_check(on_missing_data, instances=instances))

    assert {key: (group.kind, group.new_state, group.seen) for key, group in decided.items()} == expected


@pytest.mark.parametrize("on_missing_data", list(OnMissingData))
def test_a_group_the_source_cannot_judge_yet_holds_whatever_the_alerts_choice(on_missing_data: OnMissingData) -> None:
    assert _decided(_check(on_missing_data, instances=(_FIRING,)), absent=lambda key: None) == {}


@pytest.mark.parametrize(
    "last_seen_minutes_ago, fires",
    [(None, True), (1, False), (2, False), (3, True), (10, True)],
    ids=["never_seen", "first_missing_check", "second_missing_check", "third_missing_check", "long_gone"],
)
def test_breaching_counts_the_earlier_missing_checks_toward_n_of_m(
    last_seen_minutes_ago: int | None, fires: bool
) -> None:
    last_seen_at = None if last_seen_minutes_ago is None else _NOW - timedelta(minutes=last_seen_minutes_ago)
    resting = InstanceCheckState(grouping_key="", state=PlatformAlertState.NOT_FIRING.value, last_seen_at=last_seen_at)
    check = _check(OnMissingData.BREACHING, instances=(resting,), evaluation_periods=5, datapoints_to_alarm=3)

    assert _decided(check)[""].new_state == ("firing" if fires else "not_firing")
