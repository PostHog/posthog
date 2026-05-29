import datetime as dt

import pytest

from asgiref.sync import sync_to_async

from posthog.models.pulse import PulseSubscription, PulseSubscriptionFrequency
from posthog.models.scoping import team_scope
from posthog.temporal.ai.pulse.dispatcher import (
    build_child_workflow_id,
    build_scan_inputs,
    list_eligible_team_ids_activity,
)


async def _create_subscription(team, *, enabled: bool, frequency: PulseSubscriptionFrequency) -> None:
    @sync_to_async
    def _create() -> None:
        with team_scope(team.id, canonical=True):
            PulseSubscription.objects.create(team=team, enabled=enabled, frequency=frequency)

    await _create()


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("flag_enabled", [True, False])
async def test_eligible_teams_respects_flag(monkeypatch, ateam, flag_enabled):
    await _create_subscription(ateam, enabled=True, frequency=PulseSubscriptionFrequency.WEEKLY)

    captured = {}

    def fake_feature_enabled(
        key,
        distinct_id,
        *,
        groups=None,
        group_properties=None,
        only_evaluate_locally=False,
        send_feature_flag_events=True,
    ):
        captured["key"] = key
        return flag_enabled

    monkeypatch.setattr(
        "posthog.temporal.ai.pulse.dispatcher.posthoganalytics.feature_enabled",
        fake_feature_enabled,
    )

    result = await list_eligible_team_ids_activity(PulseSubscriptionFrequency.WEEKLY.value, None)

    assert captured["key"] == "max-pulse"
    assert (ateam.id in result) is flag_enabled


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_eligible_teams_excludes_disabled_subscriptions(monkeypatch, ateam):
    await _create_subscription(ateam, enabled=False, frequency=PulseSubscriptionFrequency.WEEKLY)
    monkeypatch.setattr(
        "posthog.temporal.ai.pulse.dispatcher.posthoganalytics.feature_enabled",
        lambda *a, **k: True,
    )
    result = await list_eligible_team_ids_activity(PulseSubscriptionFrequency.WEEKLY.value, None)
    assert ateam.id not in result


class TestChildWorkflowIdentity:
    def test_child_id_is_deterministic_per_period(self):
        now = dt.datetime(2026, 5, 29, 14, 0, tzinfo=dt.UTC)
        a = build_child_workflow_id(42, now, PulseSubscriptionFrequency.WEEKLY)
        b = build_child_workflow_id(42, now, PulseSubscriptionFrequency.WEEKLY)
        assert a == b == "pulse-scan-42-2026-W22"

    def test_child_id_daily(self):
        now = dt.datetime(2026, 5, 29, 14, 0, tzinfo=dt.UTC)
        assert build_child_workflow_id(7, now, PulseSubscriptionFrequency.DAILY) == "pulse-scan-7-2026-05-29"

    def test_scan_inputs_carry_period(self):
        now = dt.datetime(2026, 5, 29, 14, 0, tzinfo=dt.UTC)
        inputs = build_scan_inputs(42, now, PulseSubscriptionFrequency.WEEKLY)
        assert inputs.team_id == 42
        assert inputs.period_key == "2026-W22"
        # period_end == now; period_start one week back
        assert inputs.period_end == now.isoformat()
        assert inputs.period_start == (now - dt.timedelta(days=7)).isoformat()
