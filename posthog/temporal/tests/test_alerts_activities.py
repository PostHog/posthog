import uuid
import threading
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
import time_machine
from unittest.mock import patch

from django.db import OperationalError, connection, transaction

import pytest_asyncio
from asgiref.sync import sync_to_async
from clickhouse_driver.errors import NetworkError, SocketTimeoutError
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

from posthog.constants import AvailableFeature
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseQueryMemoryLimitExceeded,
)
from posthog.models import Team, User
from posthog.slo.types import SloOperation, SloOutcome
from posthog.tasks.alerts.utils import (
    AlertEvaluationResult,
    get_alert_error_notification_recipients,
    send_notifications_for_errors,
)
from posthog.temporal.alerts.activities import (
    _evaluation_inputs_match,
    _load_alert_for_evaluation,
    cleanup_alert_checks,
    evaluate_alert,
    notify_alert,
    prepare_alert,
    record_failed_evaluation,
    retrieve_due_alerts,
)
from posthog.temporal.alerts.retry_policy import alert_timeouts
from posthog.temporal.alerts.types import (
    EvaluateAlertActivityInputs,
    NotifyAlertActivityInputs,
    PrepareAction,
    PrepareAlertActivityInputs,
    RecordFailedEvaluationActivityInputs,
    ScheduleDueAlertChecksWorkflowInputs,
    SkipReason,
)

from products.alerts.backend.evaluation.contract import AlertExtractionError
from products.alerts.backend.evaluation.validation import THRESHOLD_BOUNDS_REQUIRED_MESSAGE
from products.alerts.backend.facade.api import LLMDetectorMisconfiguredError, LLMDetectorUnavailableError
from products.alerts.backend.facade.contracts import AlertDelivery
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, Threshold
from products.product_analytics.backend.facade.models import Insight


def _email_delivery(target: str, at: str = "2026-08-11T00:00:00+00:00") -> AlertDelivery:
    return AlertDelivery(channel="email", target=target, at=at)


def _valid_trends_query() -> dict:
    return TrendsQuery(
        series=[EventsNode(event="$pageview")],
        interval=IntervalType.DAY,
        trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
    ).model_dump()


def _default_threshold_configuration() -> dict:
    return {"type": "absolute", "bounds": {"upper": 100.0}}


def _memory_limit_error() -> ClickHouseQueryMemoryLimitExceeded:
    error = ClickHouseQueryMemoryLimitExceeded()
    error.is_per_query_limit = True
    return error


async def _create_alert(
    ateam: Team,
    *,
    query: dict | None = None,
    enabled: bool = True,
    calculation_interval: str = AlertCalculationInterval.DAILY.value,
    config: dict | None = None,
    condition: dict | None = None,
    threshold_configuration: dict | None = None,
    next_check_at: datetime | None = None,
    snoozed_until: datetime | None = None,
    skip_weekend: bool = False,
    schedule_restriction: dict | None = None,
    schedule_start_time: str | None = None,
    insight_deleted: bool = False,
    state: str = AlertState.NOT_FIRING,
    detector_config: dict | None = None,
) -> AlertConfiguration:
    @sync_to_async
    def _create() -> AlertConfiguration:
        insight = Insight.objects.create(
            team=ateam,
            name="insight",
            query=query if query is not None else _valid_trends_query(),
            deleted=insight_deleted,
        )
        threshold = Threshold.objects.create(
            team=ateam,
            insight=insight,
            configuration=threshold_configuration or _default_threshold_configuration(),
        )
        alert = AlertConfiguration.objects.create(
            team=ateam,
            insight=insight,
            name="alert",
            enabled=enabled,
            calculation_interval=calculation_interval,
            config=config if config is not None else {"type": "TrendsAlertConfig", "series_index": 0},
            condition=condition if condition is not None else {"type": "absolute_value"},
            threshold=threshold,
            next_check_at=next_check_at,
            snoozed_until=snoozed_until,
            skip_weekend=skip_weekend,
            schedule_restriction=schedule_restriction,
            schedule_start_time=schedule_start_time,
            state=state,
            detector_config=detector_config,
        )
        return alert

    return await _create()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_retrieve_due_alerts_limits_each_schedule_run_without_starving_other_teams(
    ateam: Team,
) -> None:
    max_alerts_per_run = 2
    for _ in range(max_alerts_per_run):
        await _create_alert(ateam, calculation_interval=AlertCalculationInterval.REAL_TIME.value)

    other_team = await sync_to_async(Team.objects.create)(
        organization_id=ateam.organization_id,
        project_id=ateam.project_id,
        name="Other team",
    )
    other_alert = await _create_alert(other_team)

    alerts = await ActivityEnvironment().run(
        retrieve_due_alerts,
        ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=max_alerts_per_run),
    )

    assert len(alerts) == max_alerts_per_run
    assert str(other_alert.id) in {alert.alert_id for alert in alerts}


@pytest_asyncio.fixture
async def alert(ateam):
    return await _create_alert(ateam)


@pytest_asyncio.fixture
async def alert_with_user(ateam, aorganization):
    @sync_to_async
    def _create() -> tuple[AlertConfiguration, User]:
        user = User.objects.create_and_join(
            organization=aorganization, email=f"alerts-{uuid.uuid4().hex[:6]}@posthog.com", password=None
        )
        insight = Insight.objects.create(team=ateam, name="insight", query=_valid_trends_query())
        threshold = Threshold.objects.create(
            team=ateam,
            insight=insight,
            configuration=_default_threshold_configuration(),
        )
        a = AlertConfiguration.objects.create(
            team=ateam,
            insight=insight,
            name="alert",
            enabled=True,
            calculation_interval=AlertCalculationInterval.DAILY.value,
            config={"type": "TrendsAlertConfig", "series_index": 0},
            condition={"type": "absolute_value"},
            threshold=threshold,
        )
        a.subscribed_users.add(user)
        return a, user

    alert, user = await _create()
    yield alert

    # User.current_organization is SET_NULL, so deleting the org/team (via the
    # ateam/aorganization fixtures) does not cascade-delete this user; the executor-thread
    # write above committed for real, so it must be cleaned up explicitly.
    await sync_to_async(user.delete)()


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
class TestRetrieveDueAlerts:
    @time_machine.travel("2026-09-09T12:00:00Z", tick=False)
    async def test_records_metrics_for_due_alerts(self, ateam) -> None:
        due_alert = await _create_alert(ateam, next_check_at=datetime(2026, 9, 9, 11, 0, tzinfo=UTC))
        await _create_alert(ateam, next_check_at=datetime(2026, 9, 9, 13, 0, tzinfo=UTC))

        with patch("posthog.temporal.alerts.activities.record_due_insight_alert_metrics") as record_metrics:
            result = await ActivityEnvironment().run(retrieve_due_alerts)

        assert [item.alert_id for item in result] == [str(due_alert.id)]
        record_metrics.assert_called_once()
        due_count, oldest_due_at, polled_at = record_metrics.call_args.args
        assert due_count == 1
        assert oldest_due_at == datetime(2026, 9, 9, 11, 0, tzinfo=UTC)
        assert polled_at == datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.django_db
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
                {"skip_weekend": True, "schedule_start_time": "08:30"},
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
        ctx = time_machine.travel(frozen_time, tick=False) if frozen_time else contextlib.nullcontext()
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

    @time_machine.travel("2024-06-03T10:00:00Z", tick=False)
    async def test_snoozed_future_preserves_snoozed_until(self, ateam) -> None:
        # Separate from the parameterized set because it asserts a DB field is UNCHANGED,
        # which doesn't fit the generic "next_check_at advanced" pattern.
        snoozed = datetime(2024, 6, 3, 12, 0, tzinfo=UTC)
        a = await _create_alert(ateam, snoozed_until=snoozed, state=AlertState.SNOOZED)

        env = ActivityEnvironment()
        await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=a.pk)
        assert refreshed.snoozed_until == snoozed

    @time_machine.travel("2024-06-03T10:00:00Z", tick=False)
    async def test_snoozed_until_in_past_is_cleared_and_evaluation_proceeds(self, ateam) -> None:
        past = datetime(2024, 6, 3, 9, 0, tzinfo=UTC)
        a = await _create_alert(ateam, snoozed_until=past, state=AlertState.SNOOZED)

        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.EVALUATE
        assert result.uses_llm_detector is False

    async def test_flags_an_ai_alert_for_the_dedicated_executor(self, ateam) -> None:
        query = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            interval=IntervalType.DAY,
            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        ).model_dump()
        a = await _create_alert(ateam, query=query, detector_config={"type": "llm", "threshold": 0.7, "window": 90})

        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.EVALUATE
        assert result.uses_llm_detector is True

    async def test_auto_disable_when_threshold_bounds_empty(self, ateam) -> None:
        a = await _create_alert(
            ateam,
            threshold_configuration={"type": "absolute", "bounds": {}},
        )

        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.AUTO_DISABLE
        assert result.reason == THRESHOLD_BOUNDS_REQUIRED_MESSAGE

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=a.pk)
        assert refreshed.enabled is False
        assert refreshed.state == AlertState.ERRORED

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

    async def test_auto_disable_email_alert_when_email_is_unavailable(self, alert_with_user) -> None:
        with patch("posthog.temporal.alerts.activities.is_email_available", return_value=False):
            env = ActivityEnvironment()
            result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(alert_with_user.id)))

        assert result.action == PrepareAction.AUTO_DISABLE
        assert (
            result.reason
            == "Email delivery is unavailable on this instance. Configure email before re-enabling this alert."
        )

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=alert_with_user.pk)
        assert refreshed.enabled is False
        assert refreshed.state == AlertState.ERRORED

        check = await sync_to_async(AlertCheck.objects.get)(alert_configuration=refreshed)
        assert check.error == {"message": result.reason, "code": "email_unavailable"}

    async def test_evaluate_for_valid_alert(self, alert) -> None:
        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(alert.id)))

        assert result.action == PrepareAction.EVALUATE
        assert result.reason is None

    @pytest.mark.parametrize(
        "calculation_interval,required_feature",
        [
            pytest.param(
                AlertCalculationInterval.REAL_TIME.value,
                AvailableFeature.REAL_TIME_ALERTS,
                id="real_time",
            ),
            pytest.param(
                AlertCalculationInterval.EVERY_15_MINUTES.value,
                AvailableFeature.HIGH_FREQUENCY_ALERTS,
                id="every_15_minutes",
            ),
        ],
    )
    async def test_entitlement_gated_interval_auto_disabled_without_feature(
        self, ateam, aorganization, calculation_interval: str, required_feature: AvailableFeature
    ) -> None:
        a = await _create_alert(ateam, calculation_interval=calculation_interval)

        env = ActivityEnvironment()
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(a.id)))

        assert result.action == PrepareAction.AUTO_DISABLE
        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=a.pk)
        assert refreshed.enabled is False
        assert refreshed.state == AlertState.ERRORED

        check = await sync_to_async(AlertCheck.objects.get)(alert_configuration=refreshed)
        assert check.state == AlertState.ERRORED
        assert check.error is not None

        @sync_to_async
        def _grant_feature() -> None:
            aorganization.available_product_features = [{"key": required_feature, "name": required_feature}]
            aorganization.save()

        await _grant_feature()
        entitled = await _create_alert(ateam, calculation_interval=calculation_interval)
        result = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(entitled.id)))
        assert result.action == PrepareAction.EVALUATE


@pytest.mark.asyncio
@pytest.mark.django_db
class TestEvaluateAlert:
    @pytest.mark.parametrize("uses_llm_detector", [False, True])
    async def test_ai_checks_run_on_their_own_executor(self, alert, uses_llm_detector: bool) -> None:
        # A model call can hold a thread for a minute; it must not hold one of the shared pool's.
        thread_names: list[str] = []
        await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(
            detector_config={"type": "llm" if uses_llm_detector else "zscore"}
        )

        def _record_thread(_alert, *, evaluation_id):
            thread_names.append(threading.current_thread().name)
            return AlertEvaluationResult(value=5.0, breaches=None)

        with patch("posthog.temporal.alerts.activities.check_alert_for_insight", side_effect=_record_thread):
            env = ActivityEnvironment()
            await env.run(
                evaluate_alert,
                EvaluateAlertActivityInputs(alert_id=str(alert.id), uses_llm_detector=not uses_llm_detector),
            )

        assert thread_names[0].startswith("insight-alert-llm-evaluate") is uses_llm_detector

    @pytest.mark.parametrize(
        "changes,evaluation_error",
        [
            ({"detector_config": {"type": "llm"}}, None),
            ({"enabled": False}, None),
            ({"calculation_interval": "monthly"}, None),
            ({"detector_config": {"type": "llm"}}, ValueError("query failed")),
            ({"detector_config": {"type": "llm"}}, LLMDetectorMisconfiguredError("invalid configuration")),
            (None, None),
        ],
    )
    async def test_executor_and_evaluation_use_the_same_config_snapshot(
        self, alert, ateam, changes, evaluation_error
    ) -> None:
        await sync_to_async(AlertConfiguration.objects.filter(team=ateam, id=alert.id).update)(
            detector_config={"type": "zscore"}
        )
        thread_names: list[str] = []
        detector_types: list[str] = []

        async def _load_then_convert(inputs):
            snapshot = await _load_alert_for_evaluation(inputs)
            if changes is None:
                await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).delete)()
            else:
                await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(**changes)
            return snapshot

        def _record_thread(_alert, *, evaluation_id):
            thread_names.append(threading.current_thread().name)
            detector_types.append(_alert.detector_config["type"])
            if evaluation_error:
                raise evaluation_error
            return AlertEvaluationResult(value=5.0, breaches=None)

        with (
            patch("posthog.temporal.alerts.activities._load_alert_for_evaluation", side_effect=_load_then_convert),
            patch("posthog.temporal.alerts.activities.check_alert_for_insight", side_effect=_record_thread),
        ):
            env = ActivityEnvironment()
            result = await env.run(
                evaluate_alert,
                EvaluateAlertActivityInputs(alert_id=str(alert.id), uses_llm_detector=False, team_id=ateam.id),
            )

        assert not thread_names[0].startswith("insight-alert-llm-evaluate")
        assert detector_types == ["zscore"]
        assert result.alert_check_id is None
        assert result.should_notify is False
        assert not await sync_to_async(AlertCheck.objects.filter(alert_configuration_id=alert.id).exists)()
        if changes is not None:
            saved = await sync_to_async(AlertConfiguration.objects.get)(id=alert.id)
            assert saved.state == alert.state
            assert saved.next_check_at == alert.next_check_at

    @pytest.mark.parametrize("input_kind", ["insight", "threshold"])
    async def test_evaluation_inputs_cannot_change_between_comparison_and_save(self, alert, input_kind) -> None:
        def _change_input() -> bool:
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '100ms'")
                    if input_kind == "insight":
                        Insight.objects.filter(id=alert.insight_id).update(name="Changed metric")
                    else:
                        Threshold.objects.filter(id=alert.threshold_id).update(
                            configuration={"type": "absolute", "bounds": {"upper": 200.0}}
                        )
                return False
            except OperationalError as error:
                assert "lock timeout" in str(error)
                return True
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as writer:

            def _compare_while_editing(evaluated, current):
                assert writer.submit(_change_input).result(timeout=5)
                return _evaluation_inputs_match(evaluated, current)

            with (
                patch(
                    "posthog.temporal.alerts.activities._evaluation_inputs_match", side_effect=_compare_while_editing
                ),
                patch(
                    "posthog.temporal.alerts.activities.check_alert_for_insight",
                    return_value=AlertEvaluationResult(value=5.0, breaches=None),
                ),
            ):
                result = await ActivityEnvironment().run(
                    evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id))
                )

            assert result.alert_check_id is not None
            assert writer.submit(_change_input).result(timeout=5) is False

    async def test_retry_keeps_evaluation_id_after_the_schedule_advances(self, alert) -> None:
        evaluation_ids: list[str] = []
        schedules: list[datetime | None] = []

        def _record_evaluation(_alert, *, evaluation_id):
            evaluation_ids.append(evaluation_id)
            schedules.append(_alert.next_check_at)
            return AlertEvaluationResult(value=5.0, breaches=None)

        await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(next_check_at=None)
        with patch("posthog.temporal.alerts.activities.check_alert_for_insight", side_effect=_record_evaluation):
            env = ActivityEnvironment()
            inputs = EvaluateAlertActivityInputs(alert_id=str(alert.id))
            await env.run(evaluate_alert, inputs)
            await env.run(evaluate_alert, inputs)

        assert schedules[0] is None
        assert schedules[1] is not None
        assert evaluation_ids[0]
        assert evaluation_ids[0] == evaluation_ids[1]

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

    @pytest.mark.parametrize("error_type", [AlertExtractionError, LLMDetectorMisconfiguredError])
    async def test_evaluate_auto_disables_and_skips_error_tracking_on_configuration_error(
        self, alert_with_user, error_type
    ) -> None:
        with (
            patch(
                "posthog.temporal.alerts.activities.check_alert_for_insight",
                side_effect=error_type("Alert configuration is invalid"),
            ),
            patch("posthog.temporal.alerts.activities.capture_exception") as mock_capture,
            patch("posthog.tasks.alerts.utils.send_alert_email") as mock_email,
        ):
            env = ActivityEnvironment()
            result = await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert_with_user.id)))
            mock_email.assert_not_called()

        assert result.new_state == AlertState.ERRORED
        assert result.should_notify is True
        mock_capture.assert_not_called()

        check = await sync_to_async(AlertCheck.objects.get)(pk=result.alert_check_id)
        assert check.state == AlertState.ERRORED
        assert check.error is not None
        assert "Alert configuration is invalid" in check.error["message"]

        refreshed = await sync_to_async(AlertConfiguration.objects.get)(pk=alert_with_user.pk)
        assert refreshed.enabled is False

        assert result.alert_check_id is not None
        notify_inputs = NotifyAlertActivityInputs(
            alert_id=str(alert_with_user.id), alert_check_id=result.alert_check_id
        )
        with patch(
            "posthog.tasks.alerts.utils.send_alert_email", side_effect=[RuntimeError("Mail is unavailable"), None]
        ) as mock_email:
            with pytest.raises(RuntimeError, match="Mail is unavailable"):
                await env.run(notify_alert, notify_inputs)
            await env.run(notify_alert, notify_inputs)
            await env.run(notify_alert, notify_inputs)
        assert mock_email.call_count == 2
        first, second = mock_email.call_args_list
        assert first.kwargs["campaign_key"] == second.kwargs["campaign_key"]
        assert second.kwargs["template_name"] == "alert_disabled"
        assert second.kwargs["template_context"]["alert_error"] == "Alert configuration is invalid"
        await sync_to_async(check.refresh_from_db)()
        assert check.targets_notified

    # Transient CH errors bubble up so Temporal's retry policy handles them.
    # Capacity errors (codes 202/439) surface as ClickHouseAtCapacity, so that's what we simulate.
    # A server-wide or per-user memory limit is the same kind of cluster pressure: recording it as
    # an error instead sends the alert silent until its next cadence slot, an hour for hourly ones.
    @pytest.mark.parametrize(
        "error_class",
        [
            ClickHouseAtCapacity,
            ClickHouseClusterMemoryLimitExceeded,
            SocketTimeoutError,
            NetworkError,
            LLMDetectorUnavailableError,
        ],
    )
    async def test_evaluate_reraises_ch_transient_error(self, alert, error_class) -> None:
        with patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            side_effect=error_class(),
        ):
            env = ActivityEnvironment()
            with pytest.raises(error_class):
                await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))

        # No AlertCheck should have been written
        count = await sync_to_async(AlertCheck.objects.filter(alert_configuration=alert).count)()
        assert count == 0

    async def test_evaluate_records_error_when_the_query_ran_out_of_memory(self, alert) -> None:
        # The query hit its own memory ceiling, so retrying it fails identically. It has to stay on
        # the recorded-error path rather than joining the transient class above.
        with patch(
            "posthog.temporal.alerts.activities.check_alert_for_insight",
            side_effect=_memory_limit_error(),
        ):
            env = ActivityEnvironment()
            result = await env.run(evaluate_alert, EvaluateAlertActivityInputs(alert_id=str(alert.id)))

        assert result.new_state == AlertState.ERRORED

        check = await sync_to_async(AlertCheck.objects.get)(pk=result.alert_check_id)
        assert check.error is not None

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
@pytest.mark.django_db
class TestRecordFailedEvaluation:
    @pytest.mark.parametrize("change", [None, "detector", "insight", "threshold"])
    async def test_failure_only_records_against_the_prepared_inputs(self, alert, change) -> None:
        env = ActivityEnvironment()
        prepared = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(alert.id)))
        assert prepared.action == PrepareAction.EVALUATE
        assert prepared.evaluation_fingerprint
        if change == "detector":
            await sync_to_async(AlertConfiguration.objects.filter(id=alert.id).update)(
                detector_config={"type": "zscore", "threshold": 0.95, "window": 30}, next_check_at=datetime.now(UTC)
            )
        elif change == "insight":
            await sync_to_async(Insight.objects.filter(id=alert.insight_id).update)(name="Changed metric")
        elif change == "threshold":
            await sync_to_async(Threshold.objects.filter(id=alert.threshold_id).update)(
                configuration={"type": "absolute", "bounds": {"upper": 200.0}}
            )
        before = await sync_to_async(AlertConfiguration.objects.get)(id=alert.id)
        due_before = before.next_check_at
        result = await env.run(
            record_failed_evaluation,
            RecordFailedEvaluationActivityInputs(
                alert_id=str(alert.id),
                error_message="Model timed out",
                evaluation_fingerprint=prepared.evaluation_fingerprint,
                team_id=alert.team_id,
            ),
        )
        if change is None:
            assert result.alert_check_id is not None
        else:
            assert result.alert_check_id is None
            assert not result.should_notify
            await before.arefresh_from_db()
            assert before.state == alert.state
            assert before.next_check_at == due_before
            assert not await sync_to_async(AlertCheck.objects.filter(alert_configuration=alert).exists)()
            prepared_again = await env.run(prepare_alert, PrepareAlertActivityInputs(alert_id=str(alert.id)))
            if change == "detector":
                assert prepared_again.action == PrepareAction.AUTO_DISABLE
                await before.arefresh_from_db()
                assert not before.enabled
                return
            assert prepared_again.action == PrepareAction.EVALUATE
            result_again = await env.run(
                record_failed_evaluation,
                RecordFailedEvaluationActivityInputs(
                    alert_id=str(alert.id),
                    error_message="Model timed out",
                    evaluation_fingerprint=prepared_again.evaluation_fingerprint,
                    team_id=alert.team_id,
                ),
            )
            assert result_again.alert_check_id is not None

    async def test_skips_disabled_alert_without_recording_or_notifying(self, alert_with_user) -> None:
        # Disabling an alert mid-check makes evaluate_alert raise into this activity. A normal
        # disable must not become an errored check or a "could not evaluate" email to subscribers.
        await sync_to_async(AlertConfiguration.objects.filter(pk=alert_with_user.id).update)(enabled=False)

        env = ActivityEnvironment()
        result = await env.run(
            record_failed_evaluation,
            RecordFailedEvaluationActivityInputs(
                alert_id=str(alert_with_user.id),
                error_message="Alert disabled between prepare and evaluate",
            ),
        )

        assert result.alert_check_id is None
        assert result.should_notify is False
        count = await sync_to_async(AlertCheck.objects.filter(alert_configuration=alert_with_user).count)()
        assert count == 0


@pytest.mark.asyncio
@pytest.mark.django_db
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

    async def test_records_nothing_when_no_transport_accepts(self, alert_with_user) -> None:
        # Zero accepted receipts must leave the check unstamped: stamping here would
        # recreate the false "targets notified" rows the repair command exists to clear.
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with (
            patch("posthog.slo.events.posthoganalytics"),
            patch("products.alerts.backend.facade.delivery_slo.get_instance_region", return_value="US"),
            patch("posthog.tasks.alerts.utils.send_notifications_for_breaches", return_value=[]),
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

        mock_errors.assert_not_called()
        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {}
        assert refreshed.notification_sent_at is None

    async def test_sends_breach_notifications_when_firing(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with (
            patch("posthog.slo.events.posthoganalytics") as mock_slo_analytics,
            patch("products.alerts.backend.facade.delivery_slo.get_instance_region", return_value="US"),
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_breaches",
                return_value=[_email_delivery("alice@posthog.com")],
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
        assert refreshed.targets_notified == {"users": ["alice@posthog.com"], "destinations": []}
        assert refreshed.notification_sent_at is not None

        refreshed_alert = await sync_to_async(AlertConfiguration.objects.get)(pk=alert_with_user.pk)
        assert refreshed_alert.last_notified_at is not None

        completed = [
            call
            for call in mock_slo_analytics.capture.call_args_list
            if call.kwargs["event"] == "slo_operation_completed"
        ]
        assert len(completed) == 1
        properties = completed[0].kwargs["properties"]
        assert properties["operation"] == SloOperation.ALERT_DELIVERY
        assert properties["outcome"] == SloOutcome.SUCCESS
        assert properties["region"] == "US"
        assert properties["alert_check_id"] == str(check.id)

    async def test_firing_passes_stable_idempotency_key_to_breach_sender(self, alert_with_user) -> None:
        # MessagingRecord dedupes email retries via campaign_key; notify_alert must pass
        # the AlertCheck id so a retry reuses the same key.
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with patch(
            "posthog.tasks.alerts.utils.send_notifications_for_breaches",
            return_value=[_email_delivery("alice@posthog.com")],
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
            "notify_alert must pass alert_check.id as idempotency_key so MessagingRecord dedupes email retries"
        )

    async def test_sends_error_notifications_when_errored(self, alert_with_user) -> None:
        next_check_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
        await sync_to_async(AlertConfiguration.objects.filter(pk=alert_with_user.pk).update)(
            next_check_at=next_check_at
        )
        alert_with_user.next_check_at = next_check_at
        check = await _create_alert_check(
            alert_with_user, state=AlertState.ERRORED, error={"message": "boom.", "traceback": "..."}
        )

        with (
            patch("posthog.tasks.alerts.utils.send_notifications_for_breaches") as mock_breaches,
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_errors",
                return_value=[_email_delivery("alice@posthog.com")],
            ) as mock_errors,
            patch("posthog.temporal.alerts.activities.create_notification") as mock_create_notification,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(alert_id=str(alert_with_user.id), alert_check_id=str(check.id)),
            )

        mock_errors.assert_called_once()
        mock_breaches.assert_not_called()
        assert mock_errors.call_args.kwargs["idempotency_key"] == str(check.id)
        notification = mock_create_notification.call_args.args[0]
        assert notification.notification_type.value == "pipeline_failure"
        assert notification.priority.value == "normal"
        subscriber_id = await sync_to_async(lambda: alert_with_user.subscribed_users.get().id)()
        assert notification.target_id == str(subscriber_id)
        assert notification.resource_id == str(alert_with_user.insight.short_id)
        assert notification.source_id == str(check.id)
        assert notification.source_type is None
        assert (
            notification.source_url
            == f"/project/{alert_with_user.team_id}/insights/{alert_with_user.insight.short_id}?alert_id={alert_with_user.id}"
        )
        assert "boom. This can happen" in notification.body
        assert "boom.." not in notification.body
        assert "when PostHog has a temporary problem" in notification.body
        assert "Review the alert settings" in notification.body
        assert "PostHog will try again on August 12, 2026 at 2:30 PM UTC" in notification.body
        assert "contact support" in notification.body

        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {"users": ["alice@posthog.com"], "destinations": []}

    async def test_disabled_alert_notification_does_not_promise_a_retry(self, alert_with_user) -> None:
        check = await _create_alert_check(
            alert_with_user,
            state=AlertState.ERRORED,
            error={"message": "Insight has a breakdown.", "code": "invalid_configuration"},
        )

        with (
            patch("posthog.tasks.alerts.utils.send_notifications_for_disabled", return_value=[]),
            patch("posthog.temporal.alerts.activities.create_notification") as mock_create_notification,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(alert_id=str(alert_with_user.id), alert_check_id=str(check.id)),
            )

        notification = mock_create_notification.call_args.args[0]
        assert notification.title.endswith("was turned off")
        assert "turned this alert off" in notification.body
        assert "Insight has a breakdown." in notification.body
        assert "try again" not in notification.body

    @pytest.mark.parametrize("message", [None, "", "   "])
    async def test_error_notification_uses_fallback_for_missing_reason(self, alert_with_user, message) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.ERRORED, error={"message": message})

        with (
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_errors",
                return_value=[_email_delivery("alice@posthog.com")],
            ),
            patch("posthog.temporal.alerts.activities.create_notification") as mock_create_notification,
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(alert_id=str(alert_with_user.id), alert_check_id=str(check.id)),
            )

        notification = mock_create_notification.call_args.args[0]
        assert "Unknown error" in notification.body
        assert "None" not in notification.body

    async def test_error_email_includes_next_scheduled_check(self, alert_with_user) -> None:
        next_check_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
        await sync_to_async(AlertConfiguration.objects.filter(pk=alert_with_user.pk).update)(
            next_check_at=next_check_at
        )
        alert_with_user.next_check_at = next_check_at

        with patch("posthog.tasks.alerts.utils.send_alert_email") as mock_send_alert_email:
            deliveries = await sync_to_async(send_notifications_for_errors)(
                alert_with_user, {"message": "boom"}, "notification-key"
            )

        subscriber_email = await sync_to_async(lambda: alert_with_user.subscribed_users.get().email)()
        assert [(delivery.channel, delivery.target) for delivery in deliveries] == [("email", subscriber_email)]
        assert mock_send_alert_email.call_args.kwargs["template_context"]["next_check_at"] == next_check_at

    async def test_error_notification_does_not_include_an_unsubscribed_creator(self, alert, auser) -> None:
        await sync_to_async(AlertConfiguration.objects.filter(pk=alert.id).update)(created_by_id=auser.id)
        recipients = await sync_to_async(get_alert_error_notification_recipients)(alert)

        assert recipients == []

    async def test_error_notification_excludes_subscriber_without_insight_access(self, alert_with_user) -> None:
        with patch(
            "posthog.tasks.alerts.utils.UserAccessControl.check_access_level_for_object",
            return_value=False,
        ):
            recipients = await sync_to_async(get_alert_error_notification_recipients)(alert_with_user)

        assert recipients == []

    async def test_error_realtime_notification_failure_does_not_block_recording_delivery(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.ERRORED, error={"message": "boom"})

        with (
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_errors",
                return_value=[_email_delivery("alice@posthog.com")],
            ),
            patch("posthog.temporal.alerts.activities.create_notification", side_effect=RuntimeError("kafka down")),
        ):
            env = ActivityEnvironment()
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(alert_id=str(alert_with_user.id), alert_check_id=str(check.id)),
            )

        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {"users": ["alice@posthog.com"], "destinations": []}

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

        with (
            patch("posthog.slo.events.posthoganalytics") as mock_slo_analytics,
            patch("products.alerts.backend.facade.delivery_slo.get_instance_region", return_value="US"),
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_breaches",
                side_effect=RuntimeError("SMTP unavailable"),
            ),
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

        completed = [
            call
            for call in mock_slo_analytics.capture.call_args_list
            if call.kwargs["event"] == "slo_operation_completed"
        ]
        assert len(completed) == 1
        assert completed[0].kwargs["properties"]["outcome"] == SloOutcome.FAILURE

    async def test_firing_dispatches_realtime_notification(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with (
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_breaches",
                return_value=[_email_delivery("alice@posthog.com")],
            ),
            patch("posthog.temporal.alerts.activities.create_notification") as mock_create_notification,
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

        assert mock_create_notification.call_count == 1
        data = mock_create_notification.call_args.args[0]
        assert data.notification_type.value == "alert_firing"
        assert data.team_id == alert_with_user.team_id
        assert data.resource_type == "insight"
        assert data.target_type.value == "user"
        assert data.source_type.value == "insight"
        assert data.source_id == str(alert_with_user.insight.short_id)
        assert data.resource_id == str(alert_with_user.insight.short_id)
        assert data.title.startswith("Alert firing:")

    async def test_realtime_failure_does_not_break_email_path(self, alert_with_user) -> None:
        check = await _create_alert_check(alert_with_user, state=AlertState.FIRING)

        with (
            patch(
                "posthog.tasks.alerts.utils.send_notifications_for_breaches",
                return_value=[_email_delivery("alice@posthog.com")],
            ) as mock_breaches,
            patch(
                "posthog.temporal.alerts.activities.create_notification",
                side_effect=RuntimeError("kafka down"),
            ),
        ):
            env = ActivityEnvironment()
            # Must not raise; realtime dispatch swallows errors internally.
            await env.run(
                notify_alert,
                NotifyAlertActivityInputs(
                    alert_id=str(alert_with_user.id),
                    alert_check_id=str(check.id),
                    breaches=["value above threshold"],
                ),
            )

        mock_breaches.assert_called_once()
        refreshed = await sync_to_async(AlertCheck.objects.get)(pk=check.id)
        assert refreshed.targets_notified == {"users": ["alice@posthog.com"], "destinations": []}


@pytest.mark.parametrize("calculation_interval", [None, AlertCalculationInterval.REAL_TIME])
def test_cluster_memory_limit_stays_retryable_for_the_evaluate_policy(calculation_interval) -> None:
    # The evaluate policy takes its non-retryable list from the exports user-error class names, and
    # the cluster class subclasses one of them. Listing it there too would stop every retry, so the
    # re-raise out of evaluate_alert would fail the workflow on the first attempt instead.
    policy = alert_timeouts(calculation_interval).evaluate_retry_policy
    assert ClickHouseClusterMemoryLimitExceeded.__name__ not in (policy.non_retryable_error_types or [])


@pytest.mark.asyncio
@pytest.mark.django_db
class TestCleanupAlertChecks:
    async def test_delegates_to_model_classmethod(self) -> None:
        with patch.object(AlertCheck, "clean_up_old_checks", return_value=7) as mock_cleanup:
            env = ActivityEnvironment()
            deleted = await env.run(cleanup_alert_checks)

        mock_cleanup.assert_called_once()
        assert deleted == 7
