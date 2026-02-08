from parameterized import parameterized

from posthog.dags.sessions import tags_for_sessions_partition


class TestTagsForSessionsPartition:
    @parameterized.expand(
        [
            # (partition_key, expected_partition_0, expected_partition_1)
            # Mid-month: both tags have same value
            ("2025-10-15", "s0_202510", "s1_202510"),
            # End of month: both tags have same value
            ("2025-10-31", "s0_202510", "s1_202510"),
            # First of month: tags differ (current month and previous month)
            ("2025-11-01", "s0_202511", "s1_202510"),
            # Day after first: both tags have same value again
            ("2025-11-02", "s0_202511", "s1_202511"),
            # January 1st: crosses year boundary
            ("2025-01-01", "s0_202501", "s1_202412"),
            # Another first of month
            ("2025-12-01", "s0_202512", "s1_202511"),
        ]
    )
    def test_tags_for_sessions_partition(self, partition_key, expected_partition_0, expected_partition_1):
        result = tags_for_sessions_partition(partition_key)

        assert result == {
            "sessions_db_partition_0": expected_partition_0,
            "sessions_db_partition_1": expected_partition_1,
        }
