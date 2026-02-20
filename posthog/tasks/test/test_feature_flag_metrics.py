from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry

from posthog.models import FeatureFlag, Team
from posthog.models.organization import Organization
from posthog.tasks.feature_flags import compute_feature_flag_metrics


class TestComputeFeatureFlagMetrics(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.registry = CollectorRegistry()
        self.mock_context = MagicMock()
        self.mock_context.__enter__ = MagicMock(return_value=self.registry)
        self.mock_context.__exit__ = MagicMock(return_value=False)
        self.patcher = patch("posthog.tasks.utils.pushed_metrics_registry", return_value=self.mock_context)
        self.patcher.start()
        self.settings_patcher = patch(
            "posthog.tasks.feature_flags.settings.PROM_PUSHGATEWAY_ADDRESS", "http://localhost:9091"
        )
        self.settings_patcher.start()

    def tearDown(self) -> None:
        self.settings_patcher.stop()
        self.patcher.stop()
        super().tearDown()

    def test_computes_metrics_for_single_team(self) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-1",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        compute_feature_flag_metrics()

        flag_count = self.registry.get_sample_value(
            "posthog_feature_flag_team_flag_count",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )
        assert flag_count == 1

    def test_excludes_deleted_and_inactive_flags(self) -> None:
        FeatureFlag.objects.create(
            team=self.team,
            key="active-flag",
            created_by=self.user,
            filters={"groups": []},
            active=True,
            deleted=False,
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="deleted-flag",
            created_by=self.user,
            filters={"groups": []},
            active=True,
            deleted=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="inactive-flag",
            created_by=self.user,
            filters={"groups": []},
            active=False,
            deleted=False,
        )

        compute_feature_flag_metrics()

        flag_count = self.registry.get_sample_value(
            "posthog_feature_flag_team_flag_count",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )
        assert flag_count == 1

    def test_ranks_teams_by_flag_count(self) -> None:
        org = Organization.objects.create(name="Test Org")
        team_with_many = Team.objects.create(organization=org, name="Many Flags Team")
        team_with_few = Team.objects.create(organization=org, name="Few Flags Team")

        for i in range(5):
            FeatureFlag.objects.create(
                team=team_with_many,
                key=f"flag-{i}",
                created_by=self.user,
                filters={"groups": []},
            )

        FeatureFlag.objects.create(
            team=team_with_few,
            key="single-flag",
            created_by=self.user,
            filters={"groups": []},
        )

        compute_feature_flag_metrics()

        rank1_count = self.registry.get_sample_value(
            "posthog_feature_flag_team_flag_count",
            {"rank": "1", "team_id": str(team_with_many.pk), "team_name": "Many Flags Team"},
        )
        assert rank1_count == 5

        rank2_count = self.registry.get_sample_value(
            "posthog_feature_flag_team_flag_count",
            {"rank": "2", "team_id": str(team_with_few.pk), "team_name": "Few Flags Team"},
        )
        assert rank2_count == 1

    def test_measures_largest_flag_size(self) -> None:
        large_properties = [{"key": f"prop_{i}", "value": f"value_{i}" * 100, "type": "person"} for i in range(50)]
        large_filters = {
            "groups": [
                {"properties": large_properties},
                {"rollout_percentage": 50},
            ]
        }
        FeatureFlag.objects.create(
            team=self.team,
            key="large-flag",
            created_by=self.user,
            filters=large_filters,
        )

        compute_feature_flag_metrics()

        largest_flag_bytes = self.registry.get_sample_value(
            "posthog_feature_flag_team_largest_flag_bytes",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )
        assert largest_flag_bytes is not None
        assert largest_flag_bytes > 1000

    def test_measures_total_flag_size(self) -> None:
        for i in range(3):
            FeatureFlag.objects.create(
                team=self.team,
                key=f"flag-{i}",
                created_by=self.user,
                filters={"groups": [{"properties": [{"key": "test", "value": "value"}]}]},
            )

        compute_feature_flag_metrics()

        total_size = self.registry.get_sample_value(
            "posthog_feature_flag_team_total_size_bytes",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )
        assert total_size is not None
        assert total_size > 0

    def test_limits_to_top_5_teams(self) -> None:
        org = Organization.objects.create(name="Test Org")
        for i in range(7):
            team = Team.objects.create(organization=org, name=f"Team {i}")
            for j in range(i + 1):
                FeatureFlag.objects.create(
                    team=team,
                    key=f"flag-{j}",
                    created_by=self.user,
                    filters={"groups": []},
                )

        compute_feature_flag_metrics()

        for rank in range(1, 6):
            samples = [
                sample
                for metric in self.registry.collect()
                if hasattr(metric, "samples")
                for sample in metric.samples
                if sample.name == "posthog_feature_flag_team_flag_count" and sample.labels.get("rank") == str(rank)
            ]
            assert len(samples) == 1

        for rank in [6, 7]:
            samples = [
                sample
                for metric in self.registry.collect()
                if hasattr(metric, "samples")
                for sample in metric.samples
                if sample.name == "posthog_feature_flag_team_flag_count" and sample.labels.get("rank") == str(rank)
            ]
            assert len(samples) == 0

    def test_handles_team_with_no_name(self) -> None:
        org = Organization.objects.create(name="Test Org")
        team_no_name = Team.objects.create(organization=org, name="")
        FeatureFlag.objects.create(
            team=team_no_name,
            key="flag-1",
            created_by=self.user,
            filters={"groups": []},
        )

        compute_feature_flag_metrics()

        flag_count = self.registry.get_sample_value(
            "posthog_feature_flag_team_flag_count",
            {"rank": "1", "team_id": str(team_no_name.pk), "team_name": "Unknown"},
        )
        assert flag_count == 1

    def test_handles_empty_database(self) -> None:
        FeatureFlag.objects.all().delete()

        compute_feature_flag_metrics()

        samples = list(self.registry.collect())
        flag_count_samples = [
            sample
            for metric in samples
            if hasattr(metric, "samples")
            for sample in metric.samples
            if sample.name == "posthog_feature_flag_team_flag_count"
        ]
        assert len(flag_count_samples) == 0

    def test_ranks_teams_by_largest_flag_size(self) -> None:
        org = Organization.objects.create(name="Test Org")
        team_large = Team.objects.create(organization=org, name="Large Flag Team")
        team_small = Team.objects.create(organization=org, name="Small Flag Team")

        # Team with small flag
        FeatureFlag.objects.create(
            team=team_small,
            key="small-flag",
            created_by=self.user,
            filters={"groups": []},
        )

        # Team with large flag
        large_properties = [{"key": f"prop_{i}", "value": f"value_{i}" * 100, "type": "person"} for i in range(50)]
        FeatureFlag.objects.create(
            team=team_large,
            key="large-flag",
            created_by=self.user,
            filters={"groups": [{"properties": large_properties}]},
        )

        compute_feature_flag_metrics()

        # Team with larger flag should be ranked first
        rank1_size = self.registry.get_sample_value(
            "posthog_feature_flag_team_largest_flag_bytes",
            {"rank": "1", "team_id": str(team_large.pk), "team_name": "Large Flag Team"},
        )
        assert rank1_size is not None
        assert rank1_size > 1000

        rank2_size = self.registry.get_sample_value(
            "posthog_feature_flag_team_largest_flag_bytes",
            {"rank": "2", "team_id": str(team_small.pk), "team_name": "Small Flag Team"},
        )
        assert rank2_size is not None
        assert rank2_size < rank1_size

    def test_ranks_teams_by_total_flag_size(self) -> None:
        org = Organization.objects.create(name="Test Org")
        team_large_total = Team.objects.create(organization=org, name="Large Total Team")
        team_small_total = Team.objects.create(organization=org, name="Small Total Team")

        # Team with small total (one small flag)
        FeatureFlag.objects.create(
            team=team_small_total,
            key="small-flag",
            created_by=self.user,
            filters={"groups": []},
        )

        # Team with large total (multiple flags with content)
        for i in range(5):
            FeatureFlag.objects.create(
                team=team_large_total,
                key=f"flag-{i}",
                created_by=self.user,
                filters={"groups": [{"properties": [{"key": f"prop_{i}", "value": "x" * 50}]}]},
            )

        compute_feature_flag_metrics()

        # Team with larger total should be ranked first
        rank1_total = self.registry.get_sample_value(
            "posthog_feature_flag_team_total_size_bytes",
            {"rank": "1", "team_id": str(team_large_total.pk), "team_name": "Large Total Team"},
        )
        assert rank1_total is not None

        rank2_total = self.registry.get_sample_value(
            "posthog_feature_flag_team_total_size_bytes",
            {"rank": "2", "team_id": str(team_small_total.pk), "team_name": "Small Total Team"},
        )
        assert rank2_total is not None
        assert rank2_total < rank1_total

    def test_limits_to_top_5_for_all_metrics(self) -> None:
        """Verify all five metrics respect the top-5 limit."""
        org = Organization.objects.create(name="Test Org")

        # Create 7 teams with varying flag counts and sizes
        for i in range(7):
            team = Team.objects.create(organization=org, name=f"Team {i}")
            # Each team gets (i+1) flags with increasing size
            for j in range(i + 1):
                FeatureFlag.objects.create(
                    team=team,
                    key=f"flag-{j}",
                    created_by=self.user,
                    filters={"groups": [{"properties": [{"key": "x", "value": "y" * (i + 1) * 10}]}]},
                )

        compute_feature_flag_metrics()

        # Check all five metrics have exactly 5 entries (ranks 1-5)
        metric_names = [
            "posthog_feature_flag_team_flag_count",
            "posthog_feature_flag_team_largest_flag_bytes",
            "posthog_feature_flag_team_largest_flag_pg_bytes",
            "posthog_feature_flag_team_total_size_bytes",
            "posthog_feature_flag_team_total_size_pg_bytes",
        ]

        for metric_name in metric_names:
            for rank in range(1, 6):
                samples = [
                    sample
                    for metric in self.registry.collect()
                    if hasattr(metric, "samples")
                    for sample in metric.samples
                    if sample.name == metric_name and sample.labels.get("rank") == str(rank)
                ]
                assert len(samples) == 1, f"Expected 1 sample for {metric_name} rank {rank}, got {len(samples)}"

            # Ranks 6 and 7 should not exist
            for rank in [6, 7]:
                samples = [
                    sample
                    for metric in self.registry.collect()
                    if hasattr(metric, "samples")
                    for sample in metric.samples
                    if sample.name == metric_name and sample.labels.get("rank") == str(rank)
                ]
                assert len(samples) == 0, f"Expected 0 samples for {metric_name} rank {rank}, got {len(samples)}"

    def test_measures_pg_column_size_for_largest_flag(self) -> None:
        """Verify pg_column_size metric is reported alongside OCTET_LENGTH for largest flag."""
        large_properties = [{"key": f"prop_{i}", "value": f"value_{i}" * 100, "type": "person"} for i in range(50)]
        large_filters = {
            "groups": [
                {"properties": large_properties},
                {"rollout_percentage": 50},
            ]
        }
        FeatureFlag.objects.create(
            team=self.team,
            key="large-flag",
            created_by=self.user,
            filters=large_filters,
        )

        compute_feature_flag_metrics()

        # Both metrics should be reported
        largest_flag_bytes = self.registry.get_sample_value(
            "posthog_feature_flag_team_largest_flag_bytes",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )
        largest_flag_pg_bytes = self.registry.get_sample_value(
            "posthog_feature_flag_team_largest_flag_pg_bytes",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )

        assert largest_flag_bytes is not None
        assert largest_flag_pg_bytes is not None
        assert largest_flag_bytes > 1000
        assert largest_flag_pg_bytes > 0
        # pg_column_size is typically smaller than OCTET_LENGTH due to TOAST compression
        # but for small data it might be larger due to header overhead

    def test_measures_pg_column_size_for_total_size(self) -> None:
        """Verify pg_column_size metric is reported alongside OCTET_LENGTH for total size."""
        for i in range(3):
            FeatureFlag.objects.create(
                team=self.team,
                key=f"flag-{i}",
                created_by=self.user,
                filters={"groups": [{"properties": [{"key": "test", "value": "value"}]}]},
            )

        compute_feature_flag_metrics()

        # Both metrics should be reported
        total_size = self.registry.get_sample_value(
            "posthog_feature_flag_team_total_size_bytes",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )
        total_pg_size = self.registry.get_sample_value(
            "posthog_feature_flag_team_total_size_pg_bytes",
            {"rank": "1", "team_id": str(self.team.pk), "team_name": self.team.name},
        )

        assert total_size is not None
        assert total_pg_size is not None
        assert total_size > 0
        assert total_pg_size > 0

    def test_skips_queries_when_pushgateway_not_configured(self) -> None:
        """Verify no expensive queries run when Pushgateway is not configured."""
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-1",
            created_by=self.user,
            filters={"groups": []},
        )

        with patch("posthog.tasks.feature_flags.settings") as mock_settings:
            mock_settings.PROM_PUSHGATEWAY_ADDRESS = ""

            compute_feature_flag_metrics()

        # Registry should have no metrics since we returned early
        samples = list(self.registry.collect())
        flag_count_samples = [
            sample
            for metric in samples
            if hasattr(metric, "samples")
            for sample in metric.samples
            if sample.name == "posthog_feature_flag_team_flag_count"
        ]
        assert len(flag_count_samples) == 0
