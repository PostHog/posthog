from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.surveys.survey import Survey
from posthog.models.insight import Insight
from posthog.models.product_intent.product_intent import (
    ProductIntent,
    calculate_product_activation,
)
from ...session_recordings.models.session_recording import SessionRecording
from posthog.test.base import BaseTest
from posthog.models.dashboard import Dashboard


class TestProductIntent(BaseTest):
    def setUp(self):
        super().setUp()
        self.product_intent = ProductIntent.objects.create(team=self.team, product_type="data_warehouse")

    def test_str_representation(self):
        self.assertEqual(str(self.product_intent), f"{self.team.name} - data_warehouse")

    def test_unique_constraint(self):
        # Test that we can't create duplicate product intents for same team/product
        with pytest.raises(Exception):
            ProductIntent.objects.create(team=self.team, product_type="data_warehouse")

    def test_can_create_intent_with_register(self):
        ProductIntent.register(self.team, "session_replay", "test", self.user)

        intent = ProductIntent.objects.filter(team=self.team, product_type="session_replay").first()
        assert intent is not None
        assert intent.contexts == {"test": 1}

        ProductIntent.register(self.team, "session_replay", "test", self.user)

        intent.refresh_from_db()

        assert intent is not None
        assert intent.contexts == {"test": 2}

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_data_warehouse_with_valid_query(self):
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        self.assertTrue(self.product_intent.has_activated_data_warehouse())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_data_warehouse_with_excluded_table(self):
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM events"}}
        )

        self.assertFalse(self.product_intent.has_activated_data_warehouse())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_data_warehouse_with_old_insight(self):
        with freeze_time("2024-05-15T12:00:00Z"):  # Before June 1st, 2024
            Insight.objects.create(
                team=self.team,
                query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}},
            )

        self.assertFalse(self.product_intent.has_activated_data_warehouse())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_check_and_update_activation_sets_activated_at(self):
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        self.assertIsNone(self.product_intent.activated_at)
        self.product_intent.check_and_update_activation()
        self.product_intent.refresh_from_db()
        assert self.product_intent.activated_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    @freeze_time("2024-06-15T12:00:00Z")
    def test_calculate_product_activation_task(self):
        # Create an insight that should trigger activation
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        calculate_product_activation(self.team.id)

        self.product_intent.refresh_from_db()
        assert self.product_intent.activated_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_calculate_product_activation_respects_check_interval(self):
        # Set last checked time to recent
        self.product_intent.activation_last_checked_at = datetime.now(tz=UTC)
        self.product_intent.save()

        calculate_product_activation(self.team.id, only_calc_if_days_since_last_checked=1)

        self.product_intent.refresh_from_db()
        self.assertIsNone(self.product_intent.activated_at)

    @freeze_time("2024-06-15T12:00:00Z")
    def test_calculate_product_activation_skips_activated_products(self):
        # Set product as already activated
        self.product_intent.activated_at = datetime.now(tz=UTC)
        self.product_intent.save()

        with freeze_time(datetime.now(tz=UTC) + timedelta(days=2)):
            calculate_product_activation(self.team.id)
            self.product_intent.refresh_from_db()
            assert self.product_intent.activated_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_has_activated_experiments_with_launched_experiment(self):
        self.product_intent.product_type = "experiments"
        self.product_intent.save()

        # Create a feature flag for the experiment
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            name="Test Flag",
            filters={"groups": [{"properties": []}]},
        )

        # Create an experiment without a start date (not launched)
        Experiment.objects.create(team=self.team, name="Not launched", feature_flag=feature_flag)
        self.assertFalse(self.product_intent.has_activated_experiments())

        # Create another feature flag for the launched experiment
        launched_flag = FeatureFlag.objects.create(
            team=self.team,
            key="launched-flag",
            name="Launched Flag",
            filters={"groups": [{"properties": []}]},
        )

        # Create an experiment with a start date (launched)
        Experiment.objects.create(
            team=self.team, name="Launched", start_date=datetime.now(tz=UTC), feature_flag=launched_flag
        )
        self.assertTrue(self.product_intent.has_activated_experiments())

    def test_has_activated_feature_flags(self):
        self.product_intent.product_type = "feature_flags"
        self.product_intent.save()

        # Create a feature flag with one filter group
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-1",
            name="Flag 1",
            filters={"groups": [{"properties": [{"key": "email", "value": "test@test.com"}]}]},
        )
        self.assertFalse(self.product_intent.has_activated_feature_flags())

        # Create a feature flag with another filter group
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-2",
            name="Flag 2",
            filters={"groups": [{"properties": [{"key": "country", "value": "US"}]}]},
        )
        self.assertTrue(self.product_intent.has_activated_feature_flags())

    def test_has_activated_feature_flags_excludes_experiment_and_survey_flags(self):
        self.product_intent.product_type = "feature_flags"
        self.product_intent.save()

        # Create excluded feature flags
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="feature-flag-for-experiment-test",
            name="Feature Flag for Experiment Test",
            filters={"groups": [{"properties": [{"key": "email", "value": "test@test.com"}]}]},
        )
        Experiment.objects.create(team=self.team, name="Experiment Test", feature_flag=feature_flag)
        survey_flag = FeatureFlag.objects.create(
            team=self.team,
            key="targeting-flag-for-survey-test",
            name="Targeting flag for survey Test",
            filters={"groups": [{"properties": [{"key": "country", "value": "US"}]}]},
        )
        Survey.objects.create(team=self.team, name="Survey Test", targeting_flag=survey_flag)

        self.assertFalse(self.product_intent.has_activated_feature_flags())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_activated_session_replay_with_five_recordings_viewed_and_filters_set(self):
        # Create 5 recordings and mark them as viewed
        for i in range(5):
            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=f"session-{i}",
            )

            recording.check_viewed_for_user(self.user, save_viewed=True)

        # Create a product intent with the filters set
        ProductIntent.objects.create(
            team=self.team, product_type="session_replay", contexts={"session_replay_set_filters": 1}
        )

        self.assertTrue(self.product_intent.has_activated_session_replay())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_not_activated_session_replay_with_less_than_five_recordings(self):
        # Create a product intent with the filters set
        ProductIntent.objects.create(
            team=self.team, product_type="session_replay", contexts={"session_replay_set_filters": 1}
        )

        # Create only 4 recordings and mark them as viewed
        for i in range(4):
            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=f"session-{i}",
            )

            recording.check_viewed_for_user(self.user, save_viewed=True)

        assert self.product_intent.has_activated_session_replay() is False

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_not_activated_session_replay_with_unviewed_recordings(self):
        # Create a product intent with the filters set
        ProductIntent.objects.create(
            team=self.team, product_type="session_replay", contexts={"session_replay_set_filters": 1}
        )

        for i in range(3):
            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=f"session-{i}",
            )

            recording.check_viewed_for_user(self.user, save_viewed=True)

        for i in range(4, 6):
            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=f"session-{i}",
            )

            recording.check_viewed_for_user(self.user, save_viewed=False)

        assert self.product_intent.has_activated_session_replay() is False

    def test_has_not_activated_session_replay_without_filters_set(self):
        ProductIntent.objects.create(team=self.team, product_type="session_replay")

        assert self.product_intent.has_activated_session_replay() is False

        # Create 5 recordings and mark them as viewed
        for i in range(5):
            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=f"session-{i}",
            )

            recording.check_viewed_for_user(self.user, save_viewed=True)

        assert self.product_intent.has_activated_session_replay() is False

    def test_has_activated_product_analytics_with_all_criteria(self):
        self.product_intent.product_type = "product_analytics"
        self.product_intent.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)

        self.team.ingested_event = True
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_without_enough_insights(self):
        self.product_intent.product_type = "product_analytics"
        self.product_intent.save()

        for i in range(2):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        Dashboard.objects.create(team=self.team, name="Dashboard", created_by=self.user)
        self.team.ingested_event = True
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is False

        Insight.objects.create(team=self.team, name=f"Insight 3", created_by=self.user)

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_without_dashboard(self):
        self.product_intent.product_type = "product_analytics"
        self.product_intent.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        self.team.ingested_event = True
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is False

        Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_with_default_dashboard(self):
        self.product_intent.product_type = "product_analytics"
        self.product_intent.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        self.team.ingested_event = True
        self.team.save()

        Dashboard.objects.create(team=self.team, name="My App Dashboard")

        assert self.product_intent.has_activated_product_analytics() is False

        Dashboard.objects.create(team=self.team, name="My App Dashboard", created_by=self.user)

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_with_default_insights(self):
        self.product_intent.product_type = "product_analytics"
        self.product_intent.save()

        Dashboard.objects.create(team=self.team, name="Dashboard", created_by=self.user)
        self.team.ingested_event = True
        self.team.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}")

        assert self.product_intent.has_activated_product_analytics() is False

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_without_ingested_events(self):
        self.product_intent.product_type = "product_analytics"
        self.product_intent.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        Dashboard.objects.create(team=self.team, name="Dashboard", created_by=self.user)

        self.team.ingested_event = False
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is False

        self.team.ingested_event = True
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_activated_surveys_with_launched(self):
        self.product_intent.product_type = "surveys"
        self.product_intent.save()

        Survey.objects.create(team=self.team, name="Survey Test", start_date=datetime.now(tz=UTC))
        assert self.product_intent.has_activated_surveys() is True

    def test_has_not_activated_surveys_with_no_surveys(self):
        self.product_intent.product_type = "surveys"
        self.product_intent.save()

        assert self.product_intent.has_activated_surveys() is False

    def test_has_not_activated_surveys_with_unlaunched_survey(self):
        self.product_intent.product_type = "surveys"
        self.product_intent.save()

        Survey.objects.create(team=self.team, name="Survey Test")
        assert self.product_intent.has_activated_surveys() is False
