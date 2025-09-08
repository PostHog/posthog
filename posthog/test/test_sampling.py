from django.test import TestCase

from posthog.sampling import clamp_to_range, sample_on_property, simple_hash


class TestSampling(TestCase):
    def test_simple_hash_function(self):
        assert simple_hash("test") == simple_hash("test")
        assert simple_hash("test1") != simple_hash("test2")
        assert simple_hash("") == 0
        assert simple_hash(None) == 0
        assert simple_hash("negative?") >= 0

    def test_sample_on_property(self):
        assert sample_on_property("test", 1.0) is True
        assert sample_on_property("test", 0.0) is False

        assert sample_on_property("", 0.5) is True
        assert sample_on_property("", 0.5) is True

        # Test sampling rate is clamped to valid range
        assert sample_on_property("test", 1.5) is True  # Treat as 1.0
        assert sample_on_property("test", -0.5) is False  # Treat as 0.0

        # Test deterministic behavior
        test_string = "example.com:script-src"
        result_at_10_percent = sample_on_property(test_string, 0.1)
        # The same string should have the same sampling decision at the same rate
        assert sample_on_property(test_string, 0.1) is result_at_10_percent

    def test_clamp_to_range(self):
        assert clamp_to_range(5, 0, 10) == 5
        assert clamp_to_range(-5, 0, 10) == 0
        assert clamp_to_range(15, 0, 10) == 10

        # Test with min > max
        assert clamp_to_range(5, 10, 5) == 5  # min should be set to max internally

        # Test with non-numeric values
        assert clamp_to_range("string", 0, 10) == 10  # Should use max as default
        assert clamp_to_range(None, 0, 10) == 10  # Should use max as default

        # Test with fallback value
        assert clamp_to_range("string", 0, 10, fallback_value=5) == 5  # Should use fallback

        # Test with decimal values
        assert clamp_to_range(0.5, 0, 1) == 0.5
        assert clamp_to_range(1.5, 0, 1) == 1
