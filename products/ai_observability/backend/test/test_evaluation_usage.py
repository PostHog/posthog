import pytest
from unittest.mock import patch

from products.ai_observability.backend.evaluation_usage import capture_evaluation_usage


@pytest.mark.parametrize("failure", ["_usage_groups", "ph_background_capture"])
def test_usage_failure_does_not_fail_evaluation(failure: str) -> None:
    module = "products.ai_observability.backend.evaluation_usage"
    with patch(f"{module}._usage_groups", return_value={"organization": "org", "project": "project"}):
        with patch(f"{module}.{failure}", side_effect=RuntimeError("telemetry unavailable")):
            capture_evaluation_usage(1, "llma evaluation run recorded", {"evaluation_id": "evaluation"})
