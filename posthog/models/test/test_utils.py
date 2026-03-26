import math
from random import Random
from uuid import UUID

from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from parameterized import parameterized

from posthog.models.utils import (
    BASE57,
    convert_legacy_metric,
    convert_legacy_metrics,
    generate_random_oauth_access_token,
    generate_random_oauth_refresh_token,
    generate_random_token,
    generate_random_token_personal,
    generate_random_token_project,
    generate_random_token_secret,
    mask_key_value,
    uuid7,
    validate_rate_limit,
)


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


AMBIGUOUS_CHARS = set("01OIl")
BASE57_SET = set(BASE57)


class TestTokenGeneration:
    def test_base57_alphabet(self):
        assert BASE57 == "23456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
        assert len(BASE57) == 57
        assert not AMBIGUOUS_CHARS & set(BASE57)

    @parameterized.expand(
        [
            ("bare", generate_random_token, "", 32),
            ("project", generate_random_token_project, "phc_", 32),
            ("personal", generate_random_token_personal, "phx_", 35),
            ("secret", generate_random_token_secret, "phs_", 35),
            ("oauth_access", lambda: generate_random_oauth_access_token(None), "pha_", 32),
            ("oauth_refresh", lambda: generate_random_oauth_refresh_token(None), "phr_", 32),
        ]
    )
    def test_uses_base57_alphabet(self, _name, generator, prefix, _entropy_bytes):
        for _ in range(20):
            token = generator()
            assert token.startswith(prefix), f"Expected prefix {prefix!r}, got {token[: len(prefix)]!r}"
            body = token[len(prefix) :]
            assert set(body) <= BASE57_SET, f"Token body contains non-base57 chars: {set(body) - BASE57_SET}"
            assert set(body).isdisjoint(AMBIGUOUS_CHARS), (
                f"Token body contains ambiguous chars: {set(body) & AMBIGUOUS_CHARS}"
            )

    @parameterized.expand(
        [
            ("bare_32B", generate_random_token, "", 32),
            ("personal_35B", generate_random_token_personal, "phx_", 35),
        ]
    )
    def test_minimum_length_preserves_entropy(self, _name, generator, prefix, entropy_bytes):
        max_base57_digits = math.ceil(entropy_bytes * 8 / math.log2(57))
        for _ in range(20):
            token = generator()
            body = token[len(prefix) :]
            # randbits can produce values with leading zeros in base57, so the
            # output may be up to 1 digit shorter than the theoretical max
            assert len(body) >= max_base57_digits - 1, f"Token body too short: {len(body)} < {max_base57_digits - 1}"


def test_convert_funnel_query():
    metric = {
        "kind": "ExperimentFunnelsQuery",
        "name": "My Funnel",
        "funnels_query": {
            "series": [
                {"kind": "EventsNode", "event": "step1", "name": "Step 1"},
                {"kind": "EventsNode", "event": "step2", "name": "Step 2"},
            ]
        },
    }
    result = convert_legacy_metric(metric)
    assert result["kind"] == "ExperimentMetric"
    assert result["metric_type"] == "funnel"
    assert result["name"] == "My Funnel"
    assert len(result["series"]) == 2
    assert "name" not in result["series"][0]
    assert result["series"][0]["event"] == "step1"


def test_convert_trends_query():
    metric = {
        "kind": "ExperimentTrendsQuery",
        "name": "My Trend",
        "count_query": {
            "series": [
                {"kind": "EventsNode", "event": "$pageview", "name": "Page Views", "math_property_type": "numeric"}
            ]
        },
    }
    result = convert_legacy_metric(metric)
    assert result["kind"] == "ExperimentMetric"
    assert result["metric_type"] == "mean"
    assert result["name"] == "My Trend"
    assert "math_property_type" not in result["source"]
    assert "name" not in result["source"]
    assert result["source"]["event"] == "$pageview"


def test_convert_trends_query_with_math():
    metric = {
        "kind": "ExperimentTrendsQuery",
        "count_query": {"series": [{"kind": "EventsNode", "event": "$pageview", "name": "Page Views", "math": "sum"}]},
    }
    result = convert_legacy_metric(metric)
    assert result["source"]["name"] == "Page Views"  # name kept because math exists


def test_convert_legacy_metric_already_converted():
    metric = {"kind": "ExperimentMetric", "series": [], "metric_type": "funnel"}
    result = convert_legacy_metric(metric)
    assert result == metric


def test_convert_legacy_metric_error():
    bad_metric = {"kind": "UnknownKind"}
    try:
        convert_legacy_metric(bad_metric)
        raise AssertionError("Should have raised ValueError")
    except ValueError as e:
        assert "Unknown metric kind" in str(e)


# Only basic tests for convert_legacy_metrics
def test_convert_legacy_metrics_empty():
    assert convert_legacy_metrics([]) == []
    assert convert_legacy_metrics(None) == []


def test_convert_legacy_metrics_bulk():
    metrics = [
        {"kind": "ExperimentFunnelsQuery", "funnels_query": {"series": [{"kind": "EventsNode", "event": "foo"}]}},
        {"kind": "ExperimentTrendsQuery", "count_query": {"series": [{"kind": "EventsNode", "event": "bar"}]}},
    ]
    result = convert_legacy_metrics(metrics)
    assert len(result) == 2
    assert result[0]["kind"] == "ExperimentMetric"
    assert result[1]["kind"] == "ExperimentMetric"
