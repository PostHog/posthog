from random import Random
from uuid import UUID

from django.core.exceptions import ValidationError

from posthog.models.utils import uuid7, validate_rate_limit, mask_key_value, convert_legacy_metric
from posthog.test.base import BaseTest


class TestUUIDv7(BaseTest):
    def test_has_version_of_7(self):
        self.assertEqual(uuid7().version, 7)

    def test_can_be_deterministic(self):
        time_component = 1718800371653
        pnrg = Random(42)
        uuid = uuid7(unix_ms_time=time_component, random=pnrg)
        self.assertEqual(uuid, UUID("0190307c-4fc5-7a3b-8006-671a1c80317f"))

    def test_can_parse_date_string(self):
        time_component = "2024-06-19T13:33:37"
        pnrg = Random(42)
        uuid = uuid7(unix_ms_time=time_component, random=pnrg)
        self.assertEqual(uuid, UUID("019030b3-ef68-7a3b-8006-671a1c80317f"))


class TestValidateRateLimit(BaseTest):
    def test_rate_limit(self):
        with self.assertRaises(ValidationError):
            validate_rate_limit("1/week")

    def test_rate_limit_negative(self):
        with self.assertRaises(ValidationError):
            validate_rate_limit("-1/day")

    def test_correct_values(self):
        for v in ["1/s", "2/m", "3/h", "4/d", "5/sec", "6/min", "7/hour", "8/day"]:
            self.assertIsNone(validate_rate_limit(v), f"validate_rate_limit should not raise for {v}")


def test_mask_key_value():
    assert mask_key_value("phx_1234567891011121314151617181920") == "phx_...1920"  # Normal case
    assert mask_key_value("phx_shortenedAB") == "********"  # String shorter than 16 chars
    assert mask_key_value("phx_00000000ABCD") == "phx_...ABCD"  # Exactly 8 chars
    assert mask_key_value("") == "********"  # Empty string


def test_convert_funnel_query():
    old_query = [
        {
            "kind": "ExperimentFunnelsQuery",
            "name": "My Funnel",
            "funnels_query": {
                "series": [
                    {"kind": "EventsNode", "event": "step1", "name": "Step 1"},
                    {"kind": "EventsNode", "event": "step2", "name": "Step 2"},
                ]
            },
        }
    ]

    result = convert_legacy_metric(old_query)
    assert len(result) == 1
    assert result[0]["kind"] == "ExperimentMetric"
    assert result[0]["metric_type"] == "funnel"
    assert result[0]["name"] == "My Funnel"
    assert len(result[0]["series"]) == 2
    assert "name" not in result[0]["series"][0]
    assert result[0]["series"][0]["event"] == "step1"


def test_convert_trends_query():
    old_query = [
        {
            "kind": "ExperimentTrendsQuery",
            "name": "My Trend",
            "count_query": {
                "series": [
                    {"kind": "EventsNode", "event": "$pageview", "name": "Page Views", "math_property_type": "numeric"}
                ]
            },
        }
    ]

    result = convert_legacy_metric(old_query)
    assert len(result) == 1
    assert result[0]["kind"] == "ExperimentMetric"
    assert result[0]["metric_type"] == "mean"
    assert result[0]["name"] == "My Trend"
    assert "math_property_type" not in result[0]["source"]
    assert "name" not in result[0]["source"]
    assert result[0]["source"]["event"] == "$pageview"


def test_convert_trends_query_with_math():
    old_query = [
        {
            "kind": "ExperimentTrendsQuery",
            "count_query": {
                "series": [{"kind": "EventsNode", "event": "$pageview", "name": "Page Views", "math": "sum"}]
            },
        }
    ]

    result = convert_legacy_metric(old_query)
    assert len(result) == 1
    assert result[0]["source"]["name"] == "Page Views"  # name kept because math exists
