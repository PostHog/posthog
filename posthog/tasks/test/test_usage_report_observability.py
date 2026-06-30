from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry

from posthog.tasks.usage_report_observability import (
    UsageReportRunContext,
    UsageReportRunObserver,
    UsageReportRunProgress,
    UsageReportRunStateSnapshot,
    _push_usage_report_run_state,
)


@contextmanager
def _collect_usage_report_registry(registries: list[CollectorRegistry]) -> Iterator[CollectorRegistry]:
    registry = CollectorRegistry()
    registries.append(registry)
    yield registry


def test_usage_report_run_state_metrics_use_bounded_labels_and_bounded_job_name() -> None:
    registries: list[CollectorRegistry] = []
    context = UsageReportRunContext(
        run_id="run-123",
        source="manual",
        execution_location="toolbox",
        execution_mode="direct",
        run_scope="all_orgs",
        requested_date="2026-06-29",
        period_start=datetime(2026, 6, 29),
        period_end=datetime(2026, 6, 30),
        region="US",
        celery_task_id="celery-task-123",
        celery_retries=2,
    )
    snapshot = UsageReportRunStateSnapshot(
        context=context,
        stage="sending",
        terminal_status="none",
        stage_timestamp=1_790_000_000,
        total_orgs=3,
        total_orgs_sent=1,
        query_duration_seconds=12.5,
        failure_counts={"queue": 2},
    )

    with patch(
        "posthog.tasks.usage_report_observability.pushed_metrics_registry",
        side_effect=lambda _job_name: _collect_usage_report_registry(registries),
    ) as pushed_metrics_registry_mock:
        _push_usage_report_run_state(snapshot)

    pushed_metrics_registry_mock.assert_called_once_with(
        "legacy_usage_report_run_state_us_manual_toolbox_direct_all_orgs"
    )
    registry = registries[0]
    base_labels = {
        "region": "US",
        "source": "manual",
        "execution_location": "toolbox",
        "execution_mode": "direct",
        "run_scope": "all_orgs",
    }
    assert (
        registry.get_sample_value(
            "posthog_legacy_usage_report_current_stage",
            {**base_labels, "stage": "sending"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "posthog_legacy_usage_report_current_stage",
            {**base_labels, "stage": "querying"},
        )
        == 0
    )
    assert (
        registry.get_sample_value(
            "posthog_legacy_usage_report_terminal_status",
            {**base_labels, "terminal_status": "none"},
        )
        == 1
    )
    assert (
        registry.get_sample_value(
            "posthog_legacy_usage_report_failures",
            {**base_labels, "failure_type": "queue"},
        )
        == 2
    )
    assert (
        registry.get_sample_value(
            "posthog_legacy_usage_report_failures",
            {**base_labels, "failure_type": "capture"},
        )
        == 0
    )

    for metric in registry.collect():
        for sample in metric.samples:
            assert "run_id" not in sample.labels
            assert "requested_date" not in sample.labels
            assert "celery_task_id" not in sample.labels


def test_usage_report_run_state_sticky_timestamps_use_terminal_only_jobs() -> None:
    registries: list[CollectorRegistry] = []
    job_names: list[str] = []
    context = UsageReportRunContext(
        run_id="run-123",
        source="manual",
        execution_location="toolbox",
        execution_mode="direct",
        run_scope="all_orgs",
        requested_date="2026-06-29",
        period_start=datetime(2026, 6, 29),
        period_end=datetime(2026, 6, 30),
        region="US",
        celery_task_id=None,
        celery_retries=None,
    )
    completed_snapshot = UsageReportRunStateSnapshot(
        context=context,
        stage="terminal",
        terminal_status="completed",
        stage_timestamp=1_790_000_000,
    )
    querying_snapshot = UsageReportRunStateSnapshot(
        context=context,
        stage="querying",
        terminal_status="none",
        stage_timestamp=1_790_000_100,
    )

    def collect_registry(job_name: str) -> AbstractContextManager[CollectorRegistry]:
        job_names.append(job_name)
        return _collect_usage_report_registry(registries)

    with patch("posthog.tasks.usage_report_observability.pushed_metrics_registry", side_effect=collect_registry):
        _push_usage_report_run_state(completed_snapshot)
        _push_usage_report_run_state(querying_snapshot)

    assert job_names == [
        "legacy_usage_report_run_state_us_manual_toolbox_direct_all_orgs",
        "legacy_usage_report_run_terminal_timestamp_us_manual_toolbox_direct_all_orgs",
        "legacy_usage_report_run_success_timestamp_us_manual_toolbox_direct_all_orgs",
        "legacy_usage_report_run_state_us_manual_toolbox_direct_all_orgs",
    ]
    base_labels = {
        "region": "US",
        "source": "manual",
        "execution_location": "toolbox",
        "execution_mode": "direct",
        "run_scope": "all_orgs",
    }
    assert (
        registries[1].get_sample_value("posthog_legacy_usage_report_last_terminal_timestamp_seconds", base_labels)
        == 1_790_000_000
    )
    assert (
        registries[2].get_sample_value("posthog_legacy_usage_report_last_success_timestamp_seconds", base_labels)
        == 1_790_000_000
    )
    assert (
        registries[3].get_sample_value("posthog_legacy_usage_report_last_success_timestamp_seconds", base_labels)
        is None
    )


def test_usage_report_run_state_dry_runs_do_not_update_last_success_timestamp() -> None:
    registries: list[CollectorRegistry] = []
    job_names: list[str] = []
    context = UsageReportRunContext(
        run_id="run-123",
        source="manual",
        execution_location="toolbox",
        execution_mode="direct",
        run_scope="all_orgs",
        requested_date="2026-06-29",
        period_start=datetime(2026, 6, 29),
        period_end=datetime(2026, 6, 30),
        region="US",
        celery_task_id=None,
        celery_retries=None,
        dry_run=True,
    )

    def collect_registry(job_name: str) -> AbstractContextManager[CollectorRegistry]:
        job_names.append(job_name)
        return _collect_usage_report_registry(registries)

    with patch("posthog.tasks.usage_report_observability.pushed_metrics_registry", side_effect=collect_registry):
        _push_usage_report_run_state(
            UsageReportRunStateSnapshot(
                context=context,
                stage="terminal",
                terminal_status="completed",
                stage_timestamp=1_790_000_000,
            )
        )

    assert job_names == [
        "legacy_usage_report_run_state_us_manual_toolbox_direct_all_orgs",
        "legacy_usage_report_run_terminal_timestamp_us_manual_toolbox_direct_all_orgs",
    ]
    assert (
        registries[1].get_sample_value(
            "posthog_legacy_usage_report_last_terminal_timestamp_seconds",
            {
                "region": "US",
                "source": "manual",
                "execution_location": "toolbox",
                "execution_mode": "direct",
                "run_scope": "all_orgs",
            },
        )
        == 1_790_000_000
    )


def test_usage_report_run_state_job_name_distinguishes_filtered_runs() -> None:
    registries: list[CollectorRegistry] = []
    context = UsageReportRunContext(
        run_id="run-123",
        source="scheduled",
        execution_location="usage_report_worker",
        execution_mode="celery",
        run_scope="filtered_orgs",
        requested_date="2026-06-29",
        period_start=datetime(2026, 6, 29),
        period_end=datetime(2026, 6, 30),
        region="US",
        celery_task_id="celery-task-123",
        celery_retries=0,
    )

    with patch(
        "posthog.tasks.usage_report_observability.pushed_metrics_registry",
        side_effect=lambda _job_name: _collect_usage_report_registry(registries),
    ) as pushed_metrics_registry_mock:
        _push_usage_report_run_state(UsageReportRunStateSnapshot(context=context, stage="querying"))

    pushed_metrics_registry_mock.assert_called_once_with(
        "legacy_usage_report_run_state_us_scheduled_usage_report_worker_celery_filtered_orgs"
    )


def test_usage_report_terminal_properties_keep_total_time_compatible_with_phase_duration() -> None:
    registries: list[CollectorRegistry] = []
    context = UsageReportRunContext(
        run_id="run-123",
        source="manual",
        execution_location="toolbox",
        execution_mode="direct",
        run_scope="all_orgs",
        requested_date="2026-06-29",
        period_start=datetime(2026, 6, 29),
        period_end=datetime(2026, 6, 30),
        region="US",
        celery_task_id=None,
        celery_retries=None,
    )
    observer = UsageReportRunObserver(context=context)
    mock_posthog = MagicMock()

    with freeze_time("2026-06-30T12:00:00Z") as frozen_time:
        progress = UsageReportRunProgress.for_organizations(None)
        progress.query_duration_seconds = 10.0
        progress.queue_duration_seconds = 20.0
        frozen_time.tick(delta=timedelta(seconds=45))

        with patch(
            "posthog.tasks.usage_report_observability.pushed_metrics_registry",
            side_effect=lambda _job_name: _collect_usage_report_registry(registries),
        ):
            terminal_properties = observer.completed(mock_posthog, progress)

    complete_properties = mock_posthog.capture.call_args.kwargs["properties"]
    assert complete_properties["total_time"] == 30.0
    assert complete_properties["total_duration_seconds"] == 45.0
    assert terminal_properties["total_time"] == 30.0
    assert terminal_properties["total_duration_seconds"] == 45.0
