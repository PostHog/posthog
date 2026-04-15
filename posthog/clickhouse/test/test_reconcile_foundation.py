"""Split from a larger legacy test module for review-size control."""

# Re-exported test classes are intentionally imported for pytest discovery.
from posthog.clickhouse.test.test_reconcile_shared import (
    TestDiffDependencyOrder,
    TestDiffStateExtraColumn,
    TestDiffStateMissingColumn,
    TestDiffStateMissingTable,
    TestDiffStateMvChange,
    TestDiffStateTypeChange,
    TestManifestStepGeneration,
    TestParseDesiredState,
    TestPlanGeneratorHumanReadable,
    TestReconcileImportYamlRoundTrip,
)

__all__ = [
    "TestParseDesiredState",
    "TestDiffStateMissingTable",
    "TestDiffStateExtraColumn",
    "TestDiffStateMissingColumn",
    "TestDiffStateTypeChange",
    "TestDiffStateMvChange",
    "TestDiffDependencyOrder",
    "TestPlanGeneratorHumanReadable",
    "TestManifestStepGeneration",
    "TestReconcileImportYamlRoundTrip",
]
