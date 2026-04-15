"""Split from a larger legacy test module for review-size control."""

# Re-exported test classes are intentionally imported for pytest discovery.
from posthog.clickhouse.test.test_state_diff_shared import (
    TestDiffConvergenceDateTime64,
    TestDiffConvergenceIntervalDefault,
    TestDiffConvergenceMvSelect,
    TestNormalizeDateTime64,
    TestNormalizeDecimal,
    TestNormalizeDefault,
    TestNormalizeDefaultNestedLambdaParens,
    TestNormalizeIntervalFuncs,
    TestNormalizeLambdaParens,
    TestNormalizeMvSelect,
    TestNormalizeQuoteEscaping,
    TestNormalizeType,
    TestStripRedundantParens,
)

__all__ = [
    "TestNormalizeIntervalFuncs",
    "TestNormalizeDefault",
    "TestDiffConvergenceIntervalDefault",
    "TestNormalizeLambdaParens",
    "TestNormalizeType",
    "TestNormalizeQuoteEscaping",
    "TestNormalizeDateTime64",
    "TestNormalizeDecimal",
    "TestDiffConvergenceDateTime64",
    "TestNormalizeDefaultNestedLambdaParens",
    "TestNormalizeMvSelect",
    "TestDiffConvergenceMvSelect",
    "TestStripRedundantParens",
]
