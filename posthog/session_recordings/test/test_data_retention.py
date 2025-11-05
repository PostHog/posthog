import pytest

from posthog.models.organization import ProductFeature
from posthog.session_recordings.data_retention import (
    parse_feature_to_entitlement,
    retention_violates_entitlement,
    validate_retention_period,
)


@pytest.mark.parametrize(
    "test_feature,expected_entitlement",
    [
        (None, None),
        ({}, None),
        ({"limit": 60}, None),
        ({"unit": "months"}, None),
        ({"limit": 60, "unit": "months"}, "5y"),
        ({"limit": 60, "unit": "month"}, "5y"),
        ({"limit": 12, "unit": "months"}, "1y"),
        ({"limit": 12, "unit": "month"}, "1y"),
        ({"limit": 3, "unit": "months"}, "90d"),
        ({"limit": 3, "unit": "month"}, "90d"),
        ({"limit": 1, "unit": "months"}, "30d"),
        ({"limit": 1, "unit": "month"}, "30d"),
        ({"limit": 4, "unit": "months"}, None),
        ({"limit": 4, "unit": "month"}, None),
        ({"limit": None, "unit": "month"}, None),
        ({"limit": None, "unit": None}, None),
        ({"limit": 12, "unit": None}, None),
        ({"limit": 1, "unit": "foobar"}, None),
        ({"limit": 30, "unit": "days"}, "30d"),
        ({"limit": 30, "unit": "day"}, "30d"),
        ({"limit": 90, "unit": "days"}, "90d"),
        ({"limit": 90, "unit": "day"}, "90d"),
        ({"limit": 45, "unit": "days"}, None),
        ({"limit": 45, "unit": "day"}, None),
        ({"limit": 1, "unit": "years"}, "1y"),
        ({"limit": 1, "unit": "year"}, "1y"),
        ({"limit": 5, "unit": "years"}, "5y"),
        ({"limit": 5, "unit": "year"}, "5y"),
        ({"limit": 6, "unit": "years"}, None),
        ({"limit": 6, "unit": "year"}, None),
    ],
)
def test_parse_feature_to_entitlement(test_feature: ProductFeature | None, expected_entitlement: str | None):
    assert parse_feature_to_entitlement(test_feature) == expected_entitlement


@pytest.mark.parametrize(
    "test_retention_period,expected_result",
    [
        (None, False),
        ("", False),
        ("10days", False),
        ("30d", True),
        ("90d", True),
        ("1y", True),
        ("5y", True),
        ("6y", False),
        ("foobar", False),
    ],
)
def test_validate_retention_period(test_retention_period: str | None, expected_result: bool):
    assert validate_retention_period(test_retention_period) == expected_result


@pytest.mark.parametrize(
    "test_retention,test_entitlement,expected_result",
    [
        ("30d", "30d", False),
        ("90d", "30d", True),
        ("1y", "30d", True),
        ("5y", "30d", True),
        ("30d", "90d", False),
        ("90d", "90d", False),
        ("1y", "90d", True),
        ("5y", "90d", True),
        ("30d", "1y", False),
        ("90d", "1y", False),
        ("1y", "1y", False),
        ("5y", "1y", True),
        ("30d", "5y", False),
        ("90d", "5y", False),
        ("1y", "5y", False),
        ("5y", "5y", False),
    ],
)
def test_retention_violates_entitlement(test_retention: str, test_entitlement: str, expected_result: bool):
    assert retention_violates_entitlement(test_retention, test_entitlement) == expected_result
