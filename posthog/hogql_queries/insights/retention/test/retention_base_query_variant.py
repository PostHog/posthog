from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar, cast

from unittest.mock import patch

RETENTION_BASE_QUERY_VARIANT_PATCH_PATH = (
    "posthog.hogql_queries.insights.retention.retention_base_query_fixed."
    "retention_fixed_interval_base_query_use_dwh_variant"
)
SKIP_RETENTION_BASE_QUERY_VARIANT_COMPARISON_ATTR = "_skip_retention_base_query_variant_comparison"

Result = TypeVar("Result")
TestFunction = TypeVar("TestFunction", bound=Callable[..., Any])


def skip_retention_base_query_variant_comparison(test_fn: TestFunction) -> TestFunction:
    setattr(test_fn, SKIP_RETENTION_BASE_QUERY_VARIANT_COMPARISON_ATTR, True)
    return test_fn


class RetentionBaseQueryVariantComparisonMixin:
    retention_base_query_variant_comparison_excluded_tests: set[str] = set()

    def calculate_with_retention_base_query_variant_comparison(
        self,
        query: dict[str, Any],
        calculate: Callable[[dict[str, Any]], Result],
    ) -> Result:
        legacy_query = deepcopy(query)
        with patch(RETENTION_BASE_QUERY_VARIANT_PATCH_PATH, return_value=False):
            legacy_result = calculate(legacy_query)

        if not self.should_compare_retention_base_query_variants():
            return legacy_result

        dwh_variant_query = deepcopy(query)
        with patch(RETENTION_BASE_QUERY_VARIANT_PATCH_PATH, return_value=True):
            dwh_variant_result = calculate(dwh_variant_query)

        cast(Any, self).assertEqual(dwh_variant_result, legacy_result)
        return legacy_result

    def should_compare_retention_base_query_variants(self) -> bool:
        test_method_name = getattr(self, "_testMethodName", "")
        if test_method_name in self.retention_base_query_variant_comparison_excluded_tests:
            return False

        test_method = getattr(self, test_method_name, None)
        if getattr(test_method, SKIP_RETENTION_BASE_QUERY_VARIANT_COMPARISON_ATTR, False):
            return False

        return True
