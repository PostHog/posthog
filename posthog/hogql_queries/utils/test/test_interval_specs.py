from unittest import TestCase

from posthog.schema import IntervalType

from posthog.hogql_queries.utils.interval_specs import UnsupportedIntervalError, interval_spec


class TestIntervalSpecs(TestCase):
    def test_every_interval_type_has_a_spec(self):
        for interval in IntervalType:
            spec = interval_spec(interval)
            self.assertEqual(spec.interval_type, interval)

    def test_unknown_interval_raises_instead_of_falling_back(self):
        with self.assertRaises(UnsupportedIntervalError):
            interval_spec("fortnight")
