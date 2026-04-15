"""Split from a larger legacy test module for review-size control."""

# Re-exported test classes are intentionally imported for pytest discovery.
from posthog.clickhouse.test.test_state_diff_shared import (
    TestDiffConvergenceDistributedEmptyColumns,
    TestDiffConvergenceEnum8,
    TestDiffConvergenceKafkaMVStability,
    TestDiffConvergenceKafkaVirtualColumns,
    TestDistributedSourceWithDbPrefix,
    TestKafkaCascadeOnSelectChange,
    TestKafkaMVCascadePrevention,
    TestKafkaVirtualColumns,
)

__all__ = [
    "TestKafkaVirtualColumns",
    "TestDiffConvergenceKafkaVirtualColumns",
    "TestDiffConvergenceDistributedEmptyColumns",
    "TestDiffConvergenceKafkaMVStability",
    "TestDiffConvergenceEnum8",
    "TestKafkaMVCascadePrevention",
    "TestDistributedSourceWithDbPrefix",
    "TestKafkaCascadeOnSelectChange",
]
