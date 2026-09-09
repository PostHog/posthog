from contextlib import ExitStack

import pytest
from unittest.mock import MagicMock, patch

from redis.exceptions import RedisError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot

from products.alerts.backend.forecasting.capacity import (
    FORECAST_SIMULATION_GLOBAL_CONCURRENCY,
    ForecastCapacityUnavailable,
    ForecastEvaluationCapacityExceeded,
    ForecastSimulationCapacityExceeded,
    forecast_evaluation_slot,
    forecast_simulation_slot,
)


def test_forecast_simulation_slot_releases_global_and_team_capacity() -> None:
    global_limiter = MagicMock()
    team_limiter = MagicMock()
    global_slot = ConcurrencySlot(running_tasks_key="global", task_id="request")
    team_slot = ConcurrencySlot(running_tasks_key="team", task_id="request")
    global_limiter.use.return_value = global_slot
    team_limiter.use.return_value = team_slot

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=team_limiter),
        forecast_simulation_slot(team_id=123),
    ):
        pass

    global_limiter.release.assert_called_once_with(global_slot)
    team_limiter.release.assert_called_once_with(team_slot)


def test_forecast_simulation_slot_releases_global_capacity_when_team_is_full() -> None:
    global_limiter = MagicMock()
    team_limiter = MagicMock()
    global_slot = ConcurrencySlot(running_tasks_key="global", task_id="request")
    global_limiter.use.return_value = global_slot
    team_limiter.use.side_effect = ConcurrencyLimitExceeded("full")

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=team_limiter),
        pytest.raises(ForecastSimulationCapacityExceeded),
        forecast_simulation_slot(team_id=123),
    ):
        pass

    global_limiter.release.assert_called_once_with(global_slot)
    team_limiter.release.assert_not_called()


def test_forecast_simulation_slot_does_not_acquire_team_capacity_when_global_capacity_is_full() -> None:
    global_limiter = MagicMock()
    team_limiter = MagicMock()
    global_limiter.use.side_effect = ConcurrencyLimitExceeded("full")

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=team_limiter),
        pytest.raises(ForecastSimulationCapacityExceeded),
        forecast_simulation_slot(team_id=123),
    ):
        pass

    team_limiter.use.assert_not_called()
    global_limiter.release.assert_not_called()


def test_forecast_simulation_slot_releases_capacity_when_simulation_fails() -> None:
    global_limiter = MagicMock()
    team_limiter = MagicMock()
    global_slot = ConcurrencySlot(running_tasks_key="global", task_id="request")
    team_slot = ConcurrencySlot(running_tasks_key="team", task_id="request")
    global_limiter.use.return_value = global_slot
    team_limiter.use.return_value = team_slot

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=team_limiter),
        pytest.raises(RuntimeError, match="simulation failed"),
        forecast_simulation_slot(team_id=123),
    ):
        raise RuntimeError("simulation failed")

    global_limiter.release.assert_called_once_with(global_slot)
    team_limiter.release.assert_called_once_with(team_slot)


def test_preview_saturation_leaves_scheduled_evaluations_their_own_capacity() -> None:
    with patch("products.alerts.backend.forecasting.capacity.TEST", False), ExitStack() as previews:
        for team_id in range(1, FORECAST_SIMULATION_GLOBAL_CONCURRENCY + 1):
            previews.enter_context(forecast_simulation_slot(team_id=team_id))

        with pytest.raises(ForecastSimulationCapacityExceeded), forecast_simulation_slot(team_id=1):
            pass

        with forecast_evaluation_slot(team_id=1):
            pass


def test_scheduled_evaluation_reports_saturation_for_the_workflow_to_defer() -> None:
    global_limiter = MagicMock()
    global_limiter.use.side_effect = ConcurrencyLimitExceeded("full")

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=MagicMock()),
        pytest.raises(ForecastEvaluationCapacityExceeded),
        forecast_evaluation_slot(team_id=1),
    ):
        pass


@pytest.mark.parametrize("unreachable_limiter", ["global", "team"])
def test_forecast_simulation_slot_reports_an_unreachable_capacity_store(unreachable_limiter: str) -> None:
    global_limiter = MagicMock()
    team_limiter = MagicMock()
    global_limiter.use.return_value = ConcurrencySlot(running_tasks_key="global", task_id="request")
    team_limiter.use.return_value = ConcurrencySlot(running_tasks_key="team", task_id="request")
    limiters = {"global": global_limiter, "team": team_limiter}
    limiters[unreachable_limiter].use.side_effect = RedisError("connection refused")

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=team_limiter),
        pytest.raises(ForecastCapacityUnavailable),
        forecast_simulation_slot(team_id=123),
    ):
        pass


def test_scheduled_evaluation_does_not_read_an_unreachable_store_as_saturation() -> None:
    global_limiter = MagicMock()
    global_limiter.use.side_effect = RedisError("connection refused")

    with (
        patch("products.alerts.backend.forecasting.capacity.TEST", False),
        patch("products.alerts.backend.forecasting.capacity._get_global_limiter", return_value=global_limiter),
        patch("products.alerts.backend.forecasting.capacity._get_team_limiter", return_value=MagicMock()),
        pytest.raises(ForecastCapacityUnavailable),
        forecast_evaluation_slot(team_id=1),
    ):
        pass
