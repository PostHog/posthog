import uuid
import contextlib
from datetime import UTC, datetime

import pytest
from freezegun import freeze_time
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.schema import (
    AlertCalculationInterval,
    AlertState,
    ChartDisplayType,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.models import AlertConfiguration, Insight, User
from posthog.models.alert import AlertCheck
from posthog.tasks.alerts.utils import AlertEvaluationResult
from posthog.temporal.alerts.activities import evaluate_alert, notify_alert, prepare_alert
from posthog.temporal.alerts.types import (
    EvaluateAlertActivityInputs,
    NotifyAlertActivityInputs,
    PrepareAction,
    PrepareAlertActivityInputs,
    SkipReason,
)


def _valid_trends_query() -> dict:
    return TrendsQuery(
        series=[EventsNode(event="$pageview")],
        interval=IntervalType.DAY,
        trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
    ).model_dump()


async def _create_alert(
    ateam,
    *,
    query: dict | None = None,
    enabled: bool = True,
    calculation_interval: str = AlertCalculationInterval.DAILY.value,
    config: dict | None = None,
    condition: dict | None = None,
    next_check_at: datetime | None = None,
    snoozed_until: datetime | None = None,
    skip_weekend: bool = False,
    schedule_restriction: dict | None = None,
    insight_deleted: bool = False,
    state: str = AlertState.NOT_FIRING,
) -> AlertConfiguration:
    @sync_to_async
    def _create() -> AlertConfiguration:
        insight = Insight.objects.create(
            team=ateam,
            name="insight",
            query=query if query is not None else _valid_trends_query(),
            deleted=insight_deleted,
        )
        alert = AlertConfiguration.objects.create(
            team=ateam,
            insight=insight,
            name="alert",
            enabled=enabled,
            calculation_interval=calculation_interval,
            config=config if config is not None else {"type": "TrendsAlertConfig", "series_index": 0},
            condition=condition if condition is not None else {"type": "absolute_value"},
            next_check_at=next_check_at,
            snoozed_until=snoozed_until,
            skip_weekend=skip_weekend,
            schedule_restriction=schedule_restriction,
            state=state,
        )
        return alert

    return await _create()


@pytest_asyncio.fixture
async def alert(ateam):
    return await _create_alert(ateam)


@pytest_asyncio.fixture
async def alert_with_user(ateam, aorganization):
    @sync_to_async
    def _create() -> AlertConfiguration:
        user = User.objects.create_and_join(
            organization=aorganization, email=f"alerts-{uuid.uuid4().hex[:6]}@posthog.com", password=None
        )
        insight = Insight.objects.create(team=ateam, name="insight", query=_valid_trends_query())
        a = AlertConfiguration.objects.create(
            team=ateam,
            insight=insight,
            name="alert",
            enabled=True,
            calculation_interval=AlertCalculationInterval.DAILY.value,
            config={"type": "TrendsAlertConfig", "series_index": 0},
            condition={"type": "absolute_value"},
        )
        a.subscribed_users.add(user)
        return a

    return await _create()


async def _create_alert_check(
    alert: AlertConfiguration,
    *,
    state: str,
    targets_notified: dict | None = None,
    error: dict | None = None,
) -> AlertCheck:
    @sync_to_async
    def _create() -> AlertCheck:
        return AlertCheck.objects.create(
            alert_configuration=alert,
            calculated_value=1.0,
            condition=alert.condition,
            state=state,
            error=error,
            targets_notified=targets_notified if targets_notified is not None else {},
        )

    return await _create()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestPrepareAlert:
    async def test_skip_when_alert_not_found(self) -> None:
        env = ActivityEnvironment()
        result = await env.run(
            prepare_alert,
            PrepareAlertActivityInputs(alert_id=str(uuid.uuid4())),
        )
        assert result.action == PrepareAction.SKIP
        assert result.reason == SkipReason.NOT_FOUND

    @pytest.mark.parametrize(
        "frozen_time,setup_kwargs,expected_reason,advances_next_check_at",
        [
            pytest.param(None, {"enabled": False}, SkipReason.DISABLED, False, id="disabled"),
            pytest.param(None, {"insight_deleted": True}, SkipReason.INSIGHT_DELETED, False, id="insight_deleted"),
            pytest.param(
                "2024-06-03T10:00:00Z",
                {"next_check_at": datetime(2024, 6, 3, 11, 0, tzinfo=UTC)},
                SkipReason.NOT_DUE,
                False,
                id="not_due",
            ),
            pytest.param(
                "2024-12-21T08:00:00Z",  # Saturday
                {"skip_weekend": True},
                SkipReason.WEEKEND,
                True,
                id="weekend",
            ),
            pytest.param(
                "2024-06-03T22:30:00Z",  # inside 22:00-07:00 quiet window
                {"schedule_restriction": {"blocked_windows": [{"start": "22:00", "end": "07:00"}]}},
                SkipReason.QUIET_HOURS,
                True,
                id="quiet_hours",
            ),
            pytest.param(
                "2024-06-03T10:00:00Z",
                {
                    "snoozed_until": datetime(2024, 6, 3, 12, 0, tzinfo=UTC),
                    "state": AlertState.SNOOZED,
                },
                SkipReason.SNOOZED,
                False,
                id="snoozed_future",
            ),
        ],
    )
    async def test_skip_branches(
        self,
        ateam,
        frozen_time: str | None,
        setup_kwargs: dict,
        expected_reason: SkipReason,
        advances_next_check_at: bool,
    ) -> None:
        ctx = freeze_time(frozen_time) if frozen_time else contextlib.nullcontext()
        with ctx:
            a = await _create_alert(ateam, **setup_kwargs)
            env = ActivityEnvironment()
            result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.SKIP
        assert result.reason == expected_reason

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=a.pk)
        if advances_next_check_at:
            assert refreshed.next_check_at is not None
            # Advanced at or past the frozen "now".
            assert frozen_time is not None
            assert refreshed.next_check_at >= datetime.fromisoformat(frozen_time.replace("Z", "+00:00"))
        else:
            # Non-advancing skip branches must leave next_check_at untouched.
            assert refreshed.next_check_at == setup_kwargs.get("next_check_at")

    @freeze_time("2024-06-03T10:00:00Z")
    async def test_snoozed_future_preserves_snoozed_until(self, ateam) -> None:
        # Separate from the parameterized set because it asserts a DB field is UNCHANGED,
        # which doesn't fit the generic "next_check_at advanced" pattern.
        snoozed = datetime(2024, 6, 3, 12, 0, tzinfo=UTC)
        a = await _create_alert(ateam, snoozed_until=snoozed, state=AlertState.SNOOZED)

        env = ActivityEnvironment()
        await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=a.pk)
        assert refreshed.snoozed_until == snoozed

    @freeze_time("2024-06-03T10:00:00Z")
    async def test_snoozed_until_in_past_is_cleared_and_evaluation_proceeds(self, ateam) -> None:
        past = datetime(2024, 6, 3, 9, 0, tzinfo=UTC)
        a = await _create_alert(ateam, snoozed_until=past, state=AlertState.SNOOZED)

        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.EVALUATE

    async def test_auto_disable_when_config_invalid(self, ateam) -> None:
        # Missing required "type" in config makes validate_alert_config raise ValueError.
        a = await _create_alert(ateam, config={"series_index": 0})

        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.AUTO_DISABLE
        assert result.reason is not None

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=a.pk)
        assert refreshed.enabled is False
        assert refreshed.state == AlertState.ERRORED

        # disable_invalid_alert creates an AlertCheck row recording the disabling.
        check = await sync_to_async(AlertCheck.objects.get)(alert_configuration=refreshed)
        assert check.state == AlertState.ERRORED
        assert check.calculated_value is None
        assert check.error is not None
        assert result.reason in check.error["message"]

    async def test_evaluate_for_valid_alert(self, alert) -> None:
        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(alert.id)))

        assert result.action == PrepareAction.EVALUATE
        assert result.reason is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestEvaluateAlert:
    async def test_evaluate_not_firing_no_breaches(self, alert) -> None:
        with patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            return_value=AlertEvaluationResult(value=5.0, breaches=None),
        ):
            env = ActivityEnvironment()
            result = await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))

        assert result.new_state == AlertState.NOT_FIRING
        assert result.should_notify is False
        assert result.alert_check_id  # stringified UUID, truthy

        check = await sync_to_async(AlertCheck.objects.get)(pk=result.alert_check_id)
        assert check.state == AlertState.NOT_FIRING
        assert check.calculated_value == 5.0
        assert check.targets_notified == {}  # empty sentinel — notify_alert fills on success

    async def test_evaluate_firing_with_breaches(self, alert) -> None:
        with patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            return_value=AlertEvaluationResult(value=100.0, breaches=["value above threshold"]),
        ):
            env = ActivityEnvironment()
            result = await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))

        assert result.new_state == AlertState.FIRING
        assert result.should_notify is True

        check = await sync_to_async(AlertCheck.objects.get)(pk=result.alert_check_id)
        assert check.state == AlertState.FIRING
        assert check.targets_notified == {}

    async def test_evaluate_errored_when_permanent_exception(self, alert) -> None:
        with patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            side_effect=ValueError("insight is misconfigured"),
        ):
            env = ActivityEnvironment()
            result = await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))

        assert result.new_state == AlertState.ERRORED
        assert result.should_notify is True

        check = await sync_to_async(AlertCheck.objects.get)(pk=result.alert_check_id)
        assert check.state == AlertState.ERRORED
        assert check.error is not None
        assert "misconfigured" in check.error["message"]

        # Evaluate-time errors are transient — alert stays enabled so next run retries.
        # Only prepare-time validate_alert_config failures call disable_invalid_alert.
        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=alert.pk)
        assert refreshed.enabled is True

    async def test_evaluate_reraises_ch_transient_error(self, alert) -> None:
        # Transient CH errors bubble up so Temporal's retry policy handles them.
        with patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            side_effect=CHQueryErrorTooManySimultaneousQueries("too many"),
        ):
            env = ActivityEnvironment()
            with pytest.raises(CHQueryErrorTooManySimultaneousQueries):
                await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))

        # No AlertCheck should have been written
        count = await sync_to_async(AlertCheck.objects.filter(alert_configuration=alert).count)()
        assert count == 0

    async def test_evaluate_non_retryable_when_alert_deleted_mid_workflow(self) -> None:
        env = ActivityEnvironment()
        with pytest.raises(ApplicationError) as exc_info:
            await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(uuid.uuid4())))
        assert exc_info.value.non_retryable is True

    async def test_evaluate_non_retryable_when_alert_disabled_mid_workflow(self, alert) -> None:
        await sync_to_async(AlertConfiguration.objects.filter(pk=alert.id).update)(enabled=False)

        env = ActivityEnvironment()
        with pytest.raises(ApplicationError) as exc_info:
            await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))
        assert exc_info.value.non_retryable is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestNotifyAlert:
    async def test_noop_when_not_firing(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.NOT_FIRING)

        with (
            patch("posthog.tasks.alerts.utils.send_notifications_for_breaches") as mock_breaches,
            patch("posthog.tasks.alerts.utils.send_notifications_for_errors") as mock_errors,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(alert_id=str(alert_with_user.id), alert_check_id=str(check.id)),
            )

        mock_breaches.assert_not_called()
        mock_errors.assert_not_called()

    async def test_sends_breach_notifications_when_firing(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with (
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_breaches",
                return_value=["alice@posthog.com"],
            ) as mock_breaches,
            patch("posthog.tasks.alerts.utils.send_notifications_for_errors") as mock_errors,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(
                    alert_id=str(alert_with_user.id),
                    alert_check_id=str(check.id),
                    breaches=["value above threshold"],
                ),
            )

        mock_breaches.assert_called_once()
        mock_errors.assert_not_called()

        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {"users": ["alice@posthog.com"]}

        refreshed_alert = await sync_to_async(AlertConfiguration.objects.get)(pk=alert_with_user.pk)
        assert refreshed_alert.last_notified_at is not None

    async def test_firing_passes_stable_idempotency_key_to_breach_sender(self, alert_with_user) -> None:
        # MessagingRecord dedupes retries via campaign_key; notify_alert must pass the
        # AlertCheck id so a retry reuses the same key and the provider skips re-sending.
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with patch(
            "posthog.tasks.alerts.utils.send_notifications_for_breaches",
            return_value=["alice@posthog.com"],
        ) as mock_breaches:
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(
                    alert_id=str(alert_with_user.id),
                    alert_check_id=str(check.id),
                    breaches=["value above threshold"],
                ),
            )

        mock_breaches.assert_called_once()
        call_kwargs = mock_breaches.call_args.kwargs
        assert call_kwargs.get("idempotency_key") == str(check.id), (
            "notify_alert must pass alert_check.id as idempotency_key so MessagingRecord "
            "dedupes Temporal retries at the provider level"
        )

    async def test_sends_error_notifications_when_errored(self, alert_with_user) -> None:
        check = await _create_alert_check(
            alert_with_user, state=AlertState.ERRORED, error={"message": "boom", "traceback": "..."}
        )

        with (
            patch("posthog.tasks.alerts.utils.send_notifications_for_breaches") as mock_breaches,
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_errors",
                return_value=["alice@posthog.com"],
            ) as mock_errors,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(alert_id=str(alert_with_user.id), alert_check_id=str(check.id)),
            )

        mock_errors.assert_called_once()
        mock_breaches.assert_not_called()

        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {"users": ["alice@posthog.com"]}

    async def test_idempotent_when_already_notified(self, alert_with_user) -> None:
        # Simulate a previous successful notification by setting targets_notified.
        check = await _create_alert_check(
            alert_with_user,
            state=AlertState.FIRING,
            targets_notified={"users": ["already@notified.com"]},
        )

        with (
            patch("posthog.tasks.alerts.utils.send_notifications_for_breaches") as mock_breaches,
            patch("posthog.tasks.alerts.utils.send_notifications_for_errors") as mock_errors,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(
                    alert_id=str(alert_with_user.id),
                    alert_check_id=str(check.id),
                    breaches=["ignored — idempotent return before state match"],
                ),
            )

        mock_breaches.assert_not_called()
        mock_errors.assert_not_called()

        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {"users": ["already@notified.com"]}

    async def test_raises_when_firing_without_breaches(self, alert_with_user) -> None:
        # Guard: if the workflow forgets to pipe breaches into notify inputs, fail loudly
        # instead of sending an email with empty match_descriptions.
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        env = ActivityEnvironment()
        with pytest.raises(ValueError, match="no breaches"):
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(
                    alert_id=str(alert_with_user.id), alert_check_id=str(check.id), breaches=None
                ),
            )

    async def test_raises_on_send_failure(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with patch(
            "posthog.tasks.alerts.utils.send_notifications_for_breaches",
            side_effect=RuntimeError("SMTP unavailable"),
        ):
            env = ActivityEnvironment()
            with pytest.raises(RuntimeError):
                await env.run(
                    notify_alert,
                    NotifyAlertActivityInputs(
                        alert_id=str(alert_with_user.id),
                        alert_check_id=str(check.id),
                        breaches=["value above threshold"],
                    ),
                )

        # targets_notified stays empty so Temporal retry re-attempts delivery
        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {}
