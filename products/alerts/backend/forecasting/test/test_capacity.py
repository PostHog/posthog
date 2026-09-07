import pytest
from unittest.mock import MagicMock, patch

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot

from products.alerts.backend.forecasting.capacity import ForecastSimulationCapacityExceeded, forecast_simulation_slot


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
