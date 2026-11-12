from unittest import TestCase
from unittest.mock import patch

from prometheus_client import REGISTRY

from products.customer_analytics.backend.logic.membership_metrics import MembershipTimings


class TestMembershipTimings(TestCase):
    def test_failed_step_retains_elapsed_time_and_original_error(self) -> None:
        labels = {"job": "discovery", "step": "primary_persons", "outcome": "failure"}
        name = "customer_analytics_membership_step_seconds_sum"
        before = REGISTRY.get_sample_value(name, labels) or 0
        timings = MembershipTimings(job="discovery")
        with patch("products.customer_analytics.backend.logic.membership_metrics.monotonic", side_effect=[10, 42]):
            with self.assertRaisesRegex(RuntimeError, "identity unavailable"):
                with timings.measure("primary_persons"):
                    raise RuntimeError("identity unavailable")
        assert timings.seconds == {"primary_persons": 32}
        assert timings.failed_step == "primary_persons"
        assert REGISTRY.get_sample_value(name, labels) == before + 32

    def test_repeated_step_accumulates_duration(self) -> None:
        timings = MembershipTimings(job="discovery")
        with patch("products.customer_analytics.backend.logic.membership_metrics.monotonic", side_effect=[1, 4, 7, 12]):
            with timings.measure("read_groups"):
                pass
            with timings.measure("read_groups"):
                pass
        assert timings.seconds == {"read_groups": 8}
        assert timings.failed_step is None
