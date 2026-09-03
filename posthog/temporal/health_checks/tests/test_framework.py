from typing import Any

import pytest

from posthog.job_owners import JobOwners
from posthog.temporal.health_checks.framework import HealthCheckRegistration


def _registration(**overrides: Any) -> HealthCheckRegistration:
    fields: dict[str, Any] = {
        "name": "Stub check",
        "kind": "stub_check",
        "owner": JobOwners.TEAM_INGESTION,
        "schedule": None,
        "batch_size": 250,
        "max_concurrent": 1,
        "rollout_percentage": 1.0,
        "not_processed_threshold": 0.1,
        "dry_run": False,
        "active_since_days": 90,
        "product": None,
        "remediation": None,
    }
    fields.update(overrides)
    return HealthCheckRegistration(**fields)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rollout_percentage", 0.0),
        ("rollout_percentage", 0.01),
        ("rollout_percentage", 1.0),
        ("not_processed_threshold", 0.0),
        ("not_processed_threshold", 1.0),
    ],
)
def test_accepts_fractional_values(field: str, value: float) -> None:
    assert getattr(_registration(**{field: value}), field) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("rollout_percentage", -0.1),
        ("rollout_percentage", 50.0),
        ("not_processed_threshold", -0.1),
        ("not_processed_threshold", 2.0),
    ],
)
def test_rejects_out_of_range_fractions(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        _registration(**{field: value})
