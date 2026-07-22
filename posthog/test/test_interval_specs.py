from unittest import TestCase

from parameterized import parameterized

from posthog.schema import IntervalType

from posthog.interval_specs import UnsupportedIntervalError, interval_spec


class TestIntervalSpecs(TestCase):
    @parameterized.expand([(interval,) for interval in IntervalType])
    def test_every_interval_type_has_a_spec(self, interval: IntervalType):
        spec = interval_spec(interval)
        self.assertEqual(spec.interval_type, interval)

    def test_unknown_interval_raises_instead_of_falling_back(self):
        with self.assertRaises(UnsupportedIntervalError):
            interval_spec("fortnight")
