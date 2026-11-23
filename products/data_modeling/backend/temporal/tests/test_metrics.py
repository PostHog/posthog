import datetime as dt

from unittest.mock import MagicMock, patch

import temporalio.workflow
from parameterized import parameterized

from products.data_modeling.backend.temporal.metrics import (
    error_code,
    record_request_to_finish,
    run_trigger,
    tier_label,
)
from products.data_modeling.backend.temporal.tests.recorded_metrics import (
    REQUEST_TO_FINISH_METRIC,
    RecordedMetric,
    recorded_workflow_metrics,
)

WORKFLOW_STARTED_AT = dt.datetime(2026, 1, 1, 0, 1, 0, tzinfo=dt.UTC)
FIRST_WORKFLOW_TASK_STARTED_AT = dt.datetime(2026, 1, 1, 0, 1, 20, tzinfo=dt.UTC)
WORKFLOW_FINISHED_AT = dt.datetime(2026, 1, 1, 0, 1, 30, tzinfo=dt.UTC)


@parameterized.expand(
    [
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:3600-2026-10-21T10:00:00Z", "3600"),
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:2592000:10800-2026-10-21T03:00:00Z", "2592000"),
        ("execute-dag-trino-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:900", "900"),
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b-2026-10-21T10:00:00Z", "ad_hoc"),
        ("materialize-view-manual-run", "ad_hoc"),
        (None, "ad_hoc"),
    ]
)
def test_tier_label(workflow_id: str | None, expected: str) -> None:
    assert tier_label(workflow_id) == expected


@parameterized.expand(
    [
        (
            "[TRINO_TABLE_LOCATOR_MISSING] table invoices is not supported by the Trino backend.",
            "TRINO_TABLE_LOCATOR_MISSING",
        ),
        (
            'TrinoUserError(type=USER_ERROR, name=TYPE_MISMATCH, message="line 1:7: Cannot apply operator: date - integer", query_id=q1)',
            "TYPE_MISMATCH",
        ),
        ("Trino model execution exceeded its 360-minute deadline after 2 attempts", "DEADLINE_EXCEEDED"),
        ("Trino model execution was canceled or exceeded its deadline", "DEADLINE_EXCEEDED"),
        ("error 503: service unavailable", "HTTP_503"),
        (
            "Trino restarted while it was building this model, and all 3 attempts failed. The model's query did not cause this.",
            "ADMINISTRATIVELY_KILLED",
        ),
        ("Cannot redefine an alias with the name: TrinoUserError(type=USER_ERROR, name=TYPE_MISMATCH,", "other"),
    ]
)
def test_error_code(error: str, expected: str) -> None:
    assert error_code(error) == expected


@parameterized.expand(
    [
        ("execute-dag-0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b:3600-2026-10-21T10:00:00Z", "unknown", "scheduled"),
        ("execute-dag-0b0e2b8e-5c4f-4d47-9a51-3f4f0c1d2e3a", "manual", "manual"),
    ]
)
def test_run_trigger(workflow_id: str, requested_trigger: str, expected: str) -> None:
    assert run_trigger(workflow_id, requested_trigger) == expected


@parameterized.expand(
    [
        ("measured_from_the_request", "2026-01-01T00:00:00+00:00", None, [90.0]),
        ("measured_from_the_workflow_start_without_a_request_time", None, None, [30.0]),
        ("measured_from_the_workflow_start_when_the_request_time_does_not_parse", "yesterday", None, [30.0]),
        ("never_negative_when_the_requesting_clock_is_ahead", "2026-01-01T00:05:00+00:00", None, [0.0]),
        ("not_recorded_for_a_run_inside_a_dag_run", "2026-01-01T00:00:00+00:00", MagicMock(), []),
    ]
)
def test_record_request_to_finish(
    _name: str, requested_at: str | None, parent: MagicMock | None, expected_seconds: list[float]
) -> None:
    info = MagicMock(workflow_start_time=WORKFLOW_STARTED_AT, start_time=FIRST_WORKFLOW_TASK_STARTED_AT)
    info.parent = parent

    with (
        recorded_workflow_metrics() as recorded,
        patch.object(temporalio.workflow, "info", return_value=info),
        patch.object(temporalio.workflow, "now", return_value=WORKFLOW_FINISHED_AT),
    ):
        record_request_to_finish("manual", requested_at, engine="clickhouse", status="failed")

    assert recorded == [
        RecordedMetric(
            name=REQUEST_TO_FINISH_METRIC,
            attributes={"trigger": "manual", "engine": "clickhouse", "status": "failed"},
            value=seconds,
        )
        for seconds in expected_seconds
    ]
