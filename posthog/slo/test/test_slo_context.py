import asyncio
import inspect
import traceback
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.slo.context import (
    SLO_REPO_ROOT,
    SloSpec,
    _build_error_origin,
    get_current_slo,
    slo_operation,
    tag_current_slo,
)
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties

THIS_FILE = str(Path(__file__).resolve())


def _build_spec() -> SloSpec:
    return SloSpec(
        distinct_id="alert-123",
        area=SloArea.ANALYTIC_PLATFORM,
        operation=SloOperation.ALERT_CHECK,
        team_id=123,
        resource_id="alert-123",
    )


def _tag_from_current_slo(**props: Any) -> None:
    assert tag_current_slo(**props)


def _raise_runtime_error() -> None:
    raise RuntimeError("boom")


def _expected_origin_for(func: Any) -> str:
    source_lines, start_line = inspect.getsourcelines(func)
    raise_line_offset = next(index for index, line in enumerate(source_lines) if "raise RuntimeError" in line)
    return f"{THIS_FILE}:{start_line + raise_line_offset} in {func.__name__}"


def test_get_current_slo_returns_none_outside_operation() -> None:
    assert get_current_slo() is None
    assert not tag_current_slo(ignored=True)


@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_emits_success_with_completion_properties(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    capture = MagicMock()
    spec = _build_spec()

    with slo_operation(
        spec=spec,
        properties={"calculation_interval": "hourly"},
        capture=capture,
    ) as slo:
        assert get_current_slo() is slo
        _tag_from_current_slo(alert_state="healthy", notifications_sent=2)

    mock_emit_slo_started.assert_called_once_with(
        distinct_id="alert-123",
        properties=SloStartedProperties(
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.ALERT_CHECK,
            team_id=123,
            resource_id="alert-123",
        ),
        extra_properties={"calculation_interval": "hourly"},
        capture=capture,
    )

    mock_emit_slo_completed.assert_called_once()
    completed_kwargs = mock_emit_slo_completed.call_args.kwargs
    assert completed_kwargs["distinct_id"] == "alert-123"
    assert completed_kwargs["properties"] == SloCompletedProperties(
        area=SloArea.ANALYTIC_PLATFORM,
        operation=SloOperation.ALERT_CHECK,
        team_id=123,
        outcome=SloOutcome.SUCCESS,
        resource_id="alert-123",
        duration_ms=completed_kwargs["properties"].duration_ms,
    )
    assert completed_kwargs["extra_properties"] == {
        "calculation_interval": "hourly",
        "alert_state": "healthy",
        "notifications_sent": 2,
    }
    assert completed_kwargs["capture"] is capture
    assert completed_kwargs["properties"].duration_ms is not None
    assert completed_kwargs["properties"].duration_ms >= 0
    assert get_current_slo() is None


def test_slo_handle_tag_none_unsets_existing_key() -> None:
    from posthog.slo.context import SloHandle

    slo = SloHandle()
    slo.tag(alert_state="healthy", notifications_sent=2)
    slo.tag(alert_state=None)

    assert slo.completion_properties == {"notifications_sent": 2}


@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_emits_failure_with_automatic_error_properties(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    capture = MagicMock()
    spec = _build_spec()

    with pytest.raises(RuntimeError, match="boom"):
        with slo_operation(
            spec=spec,
            properties={"calculation_interval": "daily"},
            capture=capture,
        ):
            _raise_runtime_error()

    mock_emit_slo_started.assert_called_once()
    mock_emit_slo_completed.assert_called_once()
    completed_kwargs = mock_emit_slo_completed.call_args.kwargs
    assert completed_kwargs["properties"].outcome == SloOutcome.FAILURE
    assert completed_kwargs["extra_properties"] == {
        "calculation_interval": "daily",
        "error_type": "RuntimeError",
        "error_message": "boom",
        "error_origin": _expected_origin_for(_raise_runtime_error),
    }


def test_build_error_origin_returns_deepest_frame() -> None:
    try:
        _raise_runtime_error()
    except RuntimeError as exc:
        error_origin = _build_error_origin(exc)

    assert error_origin == _expected_origin_for(_raise_runtime_error)


def test_build_error_origin_prefers_deepest_repo_frame() -> None:
    repo_frame = traceback.FrameSummary(
        filename=str(SLO_REPO_ROOT / "posthog" / "tasks" / "alerts" / "checks.py"),
        lineno=123,
        name="check_alert",
    )
    external_frame = traceback.FrameSummary(
        filename="/usr/local/lib/python3.12/site-packages/tenacity/__init__.py",
        lineno=456,
        name="wrapped_fn",
    )

    with patch("posthog.slo.context.traceback.extract_tb", return_value=[repo_frame, external_frame]):
        error_origin = _build_error_origin(RuntimeError("boom"))

    assert error_origin == f"{repo_frame.filename}:{repo_frame.lineno} in {repo_frame.name}"


@pytest.mark.parametrize(
    "overrides,expected_outcome,expected_extra_properties",
    [
        (
            [("fail", {"reason": "partial_failure", "failed_checks": 1})],
            SloOutcome.FAILURE,
            {
                "calculation_interval": "weekly",
                "reason": "partial_failure",
                "failed_checks": 1,
            },
        ),
        (
            [
                ("fail", {"reason": "partial_failure", "failed_checks": 1}),
                ("succeed", {"recovered": True}),
            ],
            SloOutcome.SUCCESS,
            {
                "calculation_interval": "weekly",
                "reason": "partial_failure",
                "failed_checks": 1,
                "recovered": True,
            },
        ),
    ],
)
@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_allows_no_exception_outcome_override(
    mock_emit_slo_started: MagicMock,
    mock_emit_slo_completed: MagicMock,
    overrides: list[tuple[str, dict[str, object]]],
    expected_outcome: SloOutcome,
    expected_extra_properties: dict[str, object],
) -> None:
    spec = _build_spec()

    with slo_operation(spec=spec, properties={"calculation_interval": "weekly"}) as slo:
        for method_name, props in overrides:
            getattr(slo, method_name)(**props)

    mock_emit_slo_started.assert_called_once()
    mock_emit_slo_completed.assert_called_once()
    completed_kwargs = mock_emit_slo_completed.call_args.kwargs
    assert completed_kwargs["properties"].outcome == expected_outcome
    assert completed_kwargs["extra_properties"] == expected_extra_properties


@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_restores_outer_slo_when_nested(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    outer_spec = _build_spec()
    inner_spec = SloSpec(
        distinct_id="alert-456",
        area=SloArea.ANALYTIC_PLATFORM,
        operation=SloOperation.ALERT_CHECK,
        team_id=456,
        resource_id="alert-456",
    )

    with slo_operation(spec=outer_spec) as outer_slo:
        assert get_current_slo() is outer_slo

        with slo_operation(spec=inner_spec) as inner_slo:
            assert get_current_slo() is inner_slo

        assert get_current_slo() is outer_slo

    assert get_current_slo() is None
    assert mock_emit_slo_started.call_count == 2
    assert mock_emit_slo_completed.call_count == 2


@pytest.mark.asyncio
@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
async def test_slo_operation_contextvar_survives_await(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    async def _tag_after_await() -> None:
        await asyncio.sleep(0)
        assert tag_current_slo(async_stage="after_await")

    with slo_operation(spec=_build_spec()):
        await _tag_after_await()

    mock_emit_slo_started.assert_called_once()
    mock_emit_slo_completed.assert_called_once()
    assert mock_emit_slo_completed.call_args.kwargs["extra_properties"] == {"async_stage": "after_await"}
