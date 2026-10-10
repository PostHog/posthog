from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.anomaly_scoring.config import default_detector_config, effective_config
from products.alerts.backend.models import InsightAnomalyConfig

MAD_CONFIG = {"type": "mad", "threshold": 0.9, "window": 14}


class TestEffectiveAnomalyConfig(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_row", None, True, default_detector_config()),
            ("all_null_row", InsightAnomalyConfig(), True, default_detector_config()),
            ("disabled", InsightAnomalyConfig(enabled=False), False, default_detector_config()),
            ("other_detector", InsightAnomalyConfig(detector_config=MAD_CONFIG), True, MAD_CONFIG),
        ]
    )
    def test_override_merges_onto_defaults(
        self,
        _name: str,
        override: InsightAnomalyConfig | None,
        expected_enabled: bool,
        expected_detector_config: dict[str, Any],
    ) -> None:
        config = effective_config(override)

        assert config.enabled is expected_enabled
        assert config.detector_config == expected_detector_config
