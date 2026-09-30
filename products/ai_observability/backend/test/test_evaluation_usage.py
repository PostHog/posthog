import pytest
from unittest.mock import patch

from products.ai_observability.backend.evaluation_usage import (
    capture_evaluation_usage,
    evaluation_output_usage_properties,
)


@pytest.mark.parametrize(
    "output_type,config,expected",
    [
        ("boolean", {}, {"output_type": "boolean", "allows_na": False, "has_passing_rule": True}),
        ("numeric", {"min": 987654.321}, {"output_type": "numeric", "allows_na": False, "has_passing_rule": False}),
        (
            "categorical",
            {
                "options": [{"key": "private_category", "label": "Private label"}],
                "selection_mode": "multiple",
                "allows_na": True,
                "passing_rule": {"categories": []},
            },
            {
                "output_type": "categorical",
                "allows_na": True,
                "has_passing_rule": True,
                "selection_mode": "multiple",
                "category_count": 1,
            },
        ),
    ],
)
def test_output_usage_contains_only_metadata(
    output_type: str, config: dict[str, object], expected: dict[str, object]
) -> None:
    assert evaluation_output_usage_properties(output_type, config) == expected


@pytest.mark.parametrize("failure", ["_usage_groups", "ph_background_capture"])
def test_usage_failure_does_not_fail_evaluation(failure: str) -> None:
    module = "products.ai_observability.backend.evaluation_usage"
    with patch(f"{module}._usage_groups", return_value={"organization": "org", "project": "project"}):
        with patch(f"{module}.{failure}", side_effect=RuntimeError("telemetry unavailable")):
            capture_evaluation_usage(1, "llma evaluation run recorded", {"evaluation_id": "evaluation"})
