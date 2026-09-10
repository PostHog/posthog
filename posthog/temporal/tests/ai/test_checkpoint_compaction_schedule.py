from django.test import override_settings

from parameterized import parameterized

from posthog.temporal.ai.checkpoint_compaction.schedule import should_register_checkpoint_compaction_schedule


class TestCheckpointCompactionSchedule:
    @parameterized.expand(
        [
            ("US", "US", True),
            ("EU", "US", False),
            (None, "US", False),
            ("EU", "EU", True),
        ]
    )
    def test_registers_only_in_configured_cloud_region(
        self, cloud_deployment: str | None, compaction_region: str, expected: bool
    ) -> None:
        with override_settings(
            CLOUD_DEPLOYMENT=cloud_deployment,
            COMPACT_IN_REGION=compaction_region,
        ):
            assert should_register_checkpoint_compaction_schedule() is expected
