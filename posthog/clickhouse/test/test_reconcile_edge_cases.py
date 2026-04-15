"""Split from a larger legacy test module for review-size control."""

# Re-exported test classes are intentionally imported for pytest discovery.
from posthog.clickhouse.test.test_reconcile_shared import (
    TestApplyRoutesStepsToCorrectCluster,
    TestCircularInheritance,
    TestComputeDiffsConvergencePreserved,
    TestComputeDiffsEmitsDropsForRemovedTables,
    TestComputeDiffsPerCluster,
    TestComputeDiffsSharedPhysicalHost,
    TestComputeDiffsSkipsOrphanScanOnFallback,
    TestComputeDiffsTagsClusterOnDiffs,
    TestDiffStatePlaceholderMvNotDropped,
    TestDriftComparesKeyFields,
    TestEngineRequiredFieldsLint,
    TestKafkaFallbackWarning,
    TestManifestStepCarriesCluster,
    TestMergetreeOrderByLint,
    TestSatelliteRoleLint,
)

__all__ = [
    "TestCircularInheritance",
    "TestKafkaFallbackWarning",
    "TestMergetreeOrderByLint",
    "TestEngineRequiredFieldsLint",
    "TestSatelliteRoleLint",
    "TestDriftComparesKeyFields",
    "TestComputeDiffsPerCluster",
    "TestComputeDiffsEmitsDropsForRemovedTables",
    "TestComputeDiffsTagsClusterOnDiffs",
    "TestManifestStepCarriesCluster",
    "TestDiffStatePlaceholderMvNotDropped",
    "TestComputeDiffsConvergencePreserved",
    "TestApplyRoutesStepsToCorrectCluster",
    "TestComputeDiffsSkipsOrphanScanOnFallback",
    "TestComputeDiffsSharedPhysicalHost",
]
