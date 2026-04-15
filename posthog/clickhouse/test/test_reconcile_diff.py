"""Split from a larger legacy test module for review-size control."""

# Re-exported test classes are intentionally imported for pytest discovery.
from posthog.clickhouse.test.test_reconcile_shared import (
    TestCheckLegacyMigrations,
    TestClusterRegistry,
    TestDetectDrift,
    TestDetectOrphans,
    TestDistributedClusterResolution,
    TestKafkaRecreateWarning,
    TestMvSelectChange,
    TestMvSelectNormalization,
    TestReplicatedEngineExplicitZkPath,
    TestStructuralFieldDiffs,
    TestTemplates,
)

__all__ = [
    "TestMvSelectChange",
    "TestDetectOrphans",
    "TestClusterRegistry",
    "TestStructuralFieldDiffs",
    "TestReplicatedEngineExplicitZkPath",
    "TestDistributedClusterResolution",
    "TestKafkaRecreateWarning",
    "TestMvSelectNormalization",
    "TestCheckLegacyMigrations",
    "TestTemplates",
    "TestDetectDrift",
]
