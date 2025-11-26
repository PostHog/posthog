from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

import numpy as np
from parameterized import parameterized

from posthog.temporal.forecast.chronos_service import ChronosForecaster


class TestChronosForecasterDataHash:
    @parameterized.expand(
        [
            ([1.0, 2.0, 3.0],),
            ([100.5, 200.25, 300.125],),
            ([0.0, 0.0, 0.0],),
        ]
    )
    def test_compute_data_hash_returns_consistent_hash(self, values: list[float]) -> None:
        hash1 = ChronosForecaster.compute_data_hash(values)
        hash2 = ChronosForecaster.compute_data_hash(values)

        assert hash1 == hash2
        assert len(hash1) == 16

    def test_compute_data_hash_different_for_different_data(self) -> None:
        hash1 = ChronosForecaster.compute_data_hash([1.0, 2.0, 3.0])
        hash2 = ChronosForecaster.compute_data_hash([1.0, 2.0, 4.0])

        assert hash1 != hash2


class TestChronosForecastTimestamp:
    @parameterized.expand(
        [
            ("hourly", "minute", 0),
            ("hourly", "second", 0),
            ("hourly", "microsecond", 0),
            ("daily", "hour", 0),
            ("daily", "minute", 0),
            ("daily", "second", 0),
            ("monthly", "day", 1),
            ("monthly", "hour", 0),
        ]
    )
    def test_get_forecast_timestamp_truncates_correctly(
        self, interval: str, time_component: str, expected_value: int
    ) -> None:
        timestamp = ChronosForecaster.get_forecast_timestamp(interval)

        assert getattr(timestamp, time_component) == expected_value
        assert timestamp.tzinfo == UTC

    def test_get_forecast_timestamp_weekly_returns_monday(self) -> None:
        timestamp = ChronosForecaster.get_forecast_timestamp("weekly")

        assert timestamp.weekday() == 0 or (datetime.now(UTC).weekday() == 0 and timestamp.weekday() == 0)
        assert timestamp.hour == 0
        assert timestamp.minute == 0


class TestChronosForecasterModelLoading:
    def teardown_method(self) -> None:
        ChronosForecaster._model = None

    def test_get_model_loads_model_once(self) -> None:
        mock_pipeline = MagicMock()
        mock_model = MagicMock()
        mock_pipeline.from_pretrained.return_value = mock_model

        with patch.dict(
            "sys.modules", {"torch": MagicMock(float32="float32"), "chronos": MagicMock(ChronosPipeline=mock_pipeline)}
        ):
            model1 = ChronosForecaster.get_model()
            model2 = ChronosForecaster.get_model()

        assert model1 is model2
        mock_pipeline.from_pretrained.assert_called_once()

    def test_get_model_uses_correct_configuration(self) -> None:
        mock_torch = MagicMock()
        mock_torch.float32 = "float32"
        mock_pipeline = MagicMock()
        mock_pipeline.from_pretrained.return_value = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch, "chronos": MagicMock(ChronosPipeline=mock_pipeline)}):
            ChronosForecaster.get_model()

        mock_pipeline.from_pretrained.assert_called_once_with(
            "amazon/chronos-bolt-tiny",
            device_map="cpu",
            torch_dtype="float32",
        )


class TestChronosForecasterForecast:
    def teardown_method(self) -> None:
        ChronosForecaster._model = None

    @patch.object(ChronosForecaster, "get_model")
    def test_forecast_returns_tuple_of_three_floats(self, mock_get_model: MagicMock) -> None:
        mock_model = MagicMock()
        mock_forecast = MagicMock()
        mock_forecast.__getitem__ = lambda self, idx: MagicMock(
            numpy=lambda: np.array([95.0, 98.0, 100.0, 102.0, 105.0] * 20)
        )
        mock_model.predict.return_value = mock_forecast
        mock_get_model.return_value = mock_model

        mock_torch = MagicMock()
        mock_torch.tensor.return_value = MagicMock()
        mock_torch.tensor.return_value.unsqueeze.return_value = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = ChronosForecaster.forecast([100.0, 101.0, 102.0, 103.0, 104.0])

        assert isinstance(result, tuple)
        assert len(result) == 3
        predicted, lower, upper = result
        assert isinstance(predicted, float)
        assert isinstance(lower, float)
        assert isinstance(upper, float)

    @parameterized.expand(
        [
            (0.90, 5.0, 95.0),
            (0.95, 2.5, 97.5),
            (0.99, 0.5, 99.5),
        ]
    )
    @patch.object(ChronosForecaster, "get_model")
    def test_forecast_respects_confidence_level(
        self,
        confidence_level: float,
        expected_lower_percentile: float,
        expected_upper_percentile: float,
        mock_get_model: MagicMock,
    ) -> None:
        mock_model = MagicMock()
        samples = np.arange(100).astype(float)
        mock_forecast = MagicMock()
        mock_forecast.__getitem__ = lambda self, idx: MagicMock(numpy=lambda: samples)
        mock_model.predict.return_value = mock_forecast
        mock_get_model.return_value = mock_model

        mock_torch = MagicMock()
        mock_torch.tensor.return_value = MagicMock()
        mock_torch.tensor.return_value.unsqueeze.return_value = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch}):
            _, lower, upper = ChronosForecaster.forecast(
                [100.0] * 10,
                confidence_level=confidence_level,
            )

        assert lower == pytest.approx(expected_lower_percentile, rel=0.1)
        assert upper == pytest.approx(expected_upper_percentile, rel=0.1)


class TestChronosForecasterBatchForecast:
    def teardown_method(self) -> None:
        ChronosForecaster._model = None

    @patch.object(ChronosForecaster, "get_model")
    def test_forecast_batch_returns_list_of_tuples(self, mock_get_model: MagicMock) -> None:
        mock_model = MagicMock()
        mock_forecast = MagicMock()
        mock_forecast.__getitem__ = lambda self, idx: MagicMock(numpy=lambda: np.array([95.0, 100.0, 105.0] * 30))
        mock_model.predict.return_value = mock_forecast
        mock_get_model.return_value = mock_model

        mock_torch = MagicMock()
        mock_torch.tensor.return_value = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch}):
            results = ChronosForecaster.forecast_batch(
                [
                    [100.0, 101.0, 102.0],
                    [200.0, 201.0, 202.0],
                ]
            )

        assert len(results) == 2
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 3

    @patch.object(ChronosForecaster, "get_model")
    def test_forecast_batch_pads_uneven_series(self, mock_get_model: MagicMock) -> None:
        mock_model = MagicMock()
        mock_forecast = MagicMock()
        mock_forecast.__getitem__ = lambda self, idx: MagicMock(numpy=lambda: np.array([100.0] * 100))
        mock_model.predict.return_value = mock_forecast
        mock_get_model.return_value = mock_model

        captured_tensor = []

        def capture_tensor(*args, **kwargs):
            captured_tensor.append(args[0])
            return MagicMock()

        mock_torch = MagicMock()
        mock_torch.tensor.side_effect = capture_tensor

        with patch.dict("sys.modules", {"torch": mock_torch}):
            ChronosForecaster.forecast_batch(
                [
                    [1.0, 2.0, 3.0],
                    [4.0, 5.0],
                ]
            )

        assert len(captured_tensor) == 1
        padded_data = captured_tensor[0]
        assert len(padded_data[0]) == len(padded_data[1])  # Both series same length
        assert padded_data[1][0] == 0.0  # Short series padded with zeros at start


class TestChronosForecasterImportError:
    def teardown_method(self) -> None:
        ChronosForecaster._model = None

    def test_get_model_raises_import_error_with_helpful_message(self) -> None:
        ChronosForecaster._model = None

        def raise_import_error(*args, **kwargs):
            raise ImportError("No module named 'chronos'")

        mock_chronos = MagicMock()
        mock_chronos.ChronosPipeline.from_pretrained.side_effect = raise_import_error

        # Simulate the actual behavior where import fails
        import sys

        original_modules = sys.modules.copy()
        try:
            # Remove chronos and torch from modules to force reimport
            sys.modules.pop("chronos", None)
            sys.modules.pop("torch", None)

            # Patch the imports to raise an ImportError
            with patch("builtins.__import__", side_effect=ImportError("No module named 'chronos'")):
                with pytest.raises(ImportError) as exc_info:
                    ChronosForecaster.get_model()

                assert "chronos-forecasting" in str(exc_info.value)
                assert "pip install" in str(exc_info.value)
        finally:
            sys.modules.update(original_modules)
