from parameterized import parameterized

from products.alerts.backend.models.alert import derive_detector_event_fields


class TestDeriveDetectorEventFields:
    @parameterized.expand(
        [
            ("threshold", None, None, "threshold"),
            ("detector", {"type": "zscore"}, None, "detector"),
            ("forecast", None, {"type": "ForecastConfig", "engine": "prophet"}, "forecast"),
        ]
    )
    def test_alert_mode(self, _name, detector_config, forecast_config, expected_mode):
        fields = derive_detector_event_fields(detector_config, forecast_config)
        assert fields["alert_mode"] == expected_mode
