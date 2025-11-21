from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import ProductIntentContext, ProductKey

from posthog.models.dashboard import Dashboard
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.file_system.user_product_list import UserProductList
from posthog.models.insight import Insight
from posthog.models.product_intent.product_intent import ProductIntent, calculate_product_activation
from posthog.models.surveys.survey import Survey
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.utils import get_instance_realm


class TestProductIntent(BaseTest):
    def setUp(self):
        super().setUp()
        self.product_intent = ProductIntent.objects.create(team=self.team, product_type=ProductKey.DATA_WAREHOUSE)

    def test_str_representation(self):
        self.assertEqual(str(self.product_intent), f"{self.team.name} - data_warehouse")

    def test_unique_constraint(self):
        # Test that we can't create duplicate product intents for same team/product
        with pytest.raises(Exception):
            ProductIntent.objects.create(team=self.team, product_type=ProductKey.DATA_WAREHOUSE)

    def test_can_create_intent_with_register(self):
        ProductIntent.register(
            self.team, ProductKey.SESSION_REPLAY, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )
        intent = ProductIntent.objects.filter(team=self.team, product_type=ProductKey.SESSION_REPLAY).first()
        assert intent is not None
        assert intent.contexts == {ProductIntentContext.QUICK_START_PRODUCT_SELECTED: 1}

        ProductIntent.register(
            self.team, ProductKey.SESSION_REPLAY, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )
        intent.refresh_from_db()
        assert intent is not None
        assert intent.contexts == {ProductIntentContext.QUICK_START_PRODUCT_SELECTED: 2}

    @freeze_time("2024-01-01T12:00:00Z")
    def test_register_with_onboarding_sets_onboarding_completed_at(self):
        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.PRODUCT_ANALYTICS,
            context=ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY,
            user=self.user,
            is_onboarding=True,
        )

        intent = ProductIntent.objects.get(team=self.team, product_type=ProductKey.PRODUCT_ANALYTICS)
        assert intent.onboarding_completed_at == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert intent.contexts == {ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY: 1}

    @freeze_time("2024-01-01T12:00:00Z")
    def test_register_without_onboarding_does_not_set_onboarding_completed_at(self):
        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.PRODUCT_ANALYTICS,
            context=ProductIntentContext.TAXONOMIC_FILTER_EMPTY_STATE,
            user=self.user,
            is_onboarding=False,
        )

        intent = ProductIntent.objects.get(team=self.team, product_type=ProductKey.PRODUCT_ANALYTICS)
        assert intent.onboarding_completed_at is None
        assert intent.contexts == {ProductIntentContext.TAXONOMIC_FILTER_EMPTY_STATE: 1}

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
            team=self.team,
            product_type=ProductKey.SESSION_REPLAY,
            contexts={ProductIntentContext.SESSION_REPLAY_SET_FILTERS: 1},
        )

        self.assertTrue(self.product_intent.has_activated_session_replay())

    @freeze_time("2024-06-15T12:00:00Z")
    def test_has_not_activated_session_replay_with_less_than_five_recordings(self):
        # Create a product intent with the filters set
        ProductIntent.objects.create(
            team=self.team,
            product_type=ProductKey.SESSION_REPLAY,
            contexts={ProductIntentContext.SESSION_REPLAY_SET_FILTERS: 1},
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
            team=self.team,
            product_type=ProductKey.SESSION_REPLAY,
            contexts={ProductIntentContext.SESSION_REPLAY_SET_FILTERS: 1},
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
        ProductIntent.objects.create(team=self.team, product_type=ProductKey.SESSION_REPLAY)

        assert self.product_intent.has_activated_session_replay() is False

        # Create 5 recordings and mark them as viewed
        for i in range(5):
            recording = SessionRecording.objects.create(
                team=self.team,
                session_id=f"session-{i}",
            )

            recording.check_viewed_for_user(self.user, save_viewed=True)

        assert self.product_intent.has_activated_session_replay() is False

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.event_usage.report_user_action")
    def test_register_reports_correct_user_action_for_onboarding(self, mock_report_user_action):
        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.PRODUCT_ANALYTICS,
            context=ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY,
            user=self.user,
            metadata={"extra": "data"},
            is_onboarding=True,
        )

        mock_report_user_action.assert_called_once_with(
            self.user,
            "user showed product intent",
            {
                "extra": "data",
                "product_key": ProductKey.PRODUCT_ANALYTICS,
                "$set_once": {"first_onboarding_product_selected": ProductKey.PRODUCT_ANALYTICS},
                "intent_context": ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY,
                "is_first_intent_for_product": True,
                "intent_created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "intent_updated_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "realm": get_instance_realm(),
            },
            team=self.team,
        )

    @freeze_time("2024-01-01T12:00:00Z")
    @patch("posthog.event_usage.report_user_action")
    def test_register_reports_correct_user_action_for_non_onboarding(self, mock_report_user_action):
        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.PRODUCT_ANALYTICS,
            context=ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            user=self.user,
            metadata={"extra": "data"},
            is_onboarding=False,
        )

        mock_report_user_action.assert_called_once_with(
            self.user,
            "user showed product intent",
            {
                "extra": "data",
                "product_key": ProductKey.PRODUCT_ANALYTICS,
                "$set_once": {},
                "intent_context": ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
                "is_first_intent_for_product": True,
                "intent_created_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "intent_updated_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                "realm": get_instance_realm(),
            },
            team=self.team,
        )

    def test_has_activated_product_analytics_with_all_criteria(self):
        self.product_intent.product_type = ProductKey.PRODUCT_ANALYTICS
        self.product_intent.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)

        self.team.ingested_event = True
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_without_enough_insights(self):
        self.product_intent.product_type = ProductKey.PRODUCT_ANALYTICS
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
        self.product_intent.product_type = ProductKey.PRODUCT_ANALYTICS
        self.product_intent.save()

        for i in range(3):
            Insight.objects.create(team=self.team, name=f"Insight {i}", created_by=self.user)

        self.team.ingested_event = True
        self.team.save()

        assert self.product_intent.has_activated_product_analytics() is False

        Dashboard.objects.create(team=self.team, name="Test Dashboard", created_by=self.user)

        assert self.product_intent.has_activated_product_analytics() is True

    def test_has_not_activated_product_analytics_with_default_dashboard(self):
        self.product_intent.product_type = ProductKey.PRODUCT_ANALYTICS
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
        self.product_intent.product_type = ProductKey.PRODUCT_ANALYTICS
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
        self.product_intent.product_type = ProductKey.PRODUCT_ANALYTICS
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

    @freeze_time("2024-06-15T12:00:00Z")
    @patch("posthog.event_usage.report_user_action")
    def test_register_tracks_intent_even_when_already_activated(self, mock_report_user_action):
        # Create an insight that should trigger activation for data_warehouse
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )

        # Register intent which should activate immediately
        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.DATA_WAREHOUSE,
            context=ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY,
            user=self.user,
        )

        # Verify the intent was activated
        intent = ProductIntent.objects.get(team=self.team, product_type=ProductKey.DATA_WAREHOUSE)
        assert intent.activated_at is not None

        # Clear the mock to count only subsequent calls
        mock_report_user_action.reset_mock()

        # Register intent again with a different context
        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.DATA_WAREHOUSE,
            context=ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___SECONDARY,
            user=self.user,
            metadata={"source": "dashboard"},
        )

        # Verify that report_user_action was called even though the intent was already activated
        mock_report_user_action.assert_called_once_with(
            self.user,
            "user showed product intent",
            {
                "source": "dashboard",
                "product_key": ProductKey.DATA_WAREHOUSE,
                "$set_once": {},
                "intent_context": ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___SECONDARY,
                "is_first_intent_for_product": False,
                "intent_created_at": intent.created_at,
                "intent_updated_at": intent.updated_at,
                "realm": get_instance_realm(),
            },
            team=self.team,
        )

    def test_has_activated_surveys_with_launched(self):
        self.product_intent.product_type = ProductKey.SURVEYS
        self.product_intent.save()

        Survey.objects.create(team=self.team, name="Survey Test", start_date=datetime.now(tz=UTC))
        assert self.product_intent.has_activated_surveys() is True

    def test_has_not_activated_surveys_with_no_surveys(self):
        self.product_intent.product_type = ProductKey.SURVEYS
        self.product_intent.save()

        assert self.product_intent.has_activated_surveys() is False

    def test_has_not_activated_surveys_with_unlaunched_survey(self):
        self.product_intent.product_type = ProductKey.SURVEYS
        self.product_intent.save()

        Survey.objects.create(team=self.team, name="Survey Test")
        assert self.product_intent.has_activated_surveys() is False

    @freeze_time("2024-06-15T12:00:00Z")
    def test_check_and_update_activation_skips_if_already_activated(self):
        # First activate it
        Insight.objects.create(
            team=self.team, query={"kind": "DataVisualizationNode", "source": {"query": "SELECT * FROM custom_table"}}
        )
        self.product_intent.check_and_update_activation()
        initial_activated_at = self.product_intent.activated_at
        initial_last_checked = self.product_intent.activation_last_checked_at

        # Move time forward and check again
        with freeze_time("2024-06-16T12:00:00Z"):
            result = self.product_intent.check_and_update_activation()
            self.product_intent.refresh_from_db()

            assert result is True  # Returns True for already activated
            assert self.product_intent.activated_at == initial_activated_at  # Activation time unchanged
            assert self.product_intent.activation_last_checked_at == initial_last_checked  # Last checked unchanged

    @freeze_time("2024-06-15T12:00:00Z")
    def test_check_and_update_activation_updates_last_checked_for_non_activated(self):
        initial_last_checked = self.product_intent.activation_last_checked_at
        result = self.product_intent.check_and_update_activation()
        self.product_intent.refresh_from_db()

        assert result is False  # Not activated
        assert self.product_intent.activated_at is None  # Still not activated
        assert self.product_intent.activation_last_checked_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert self.product_intent.activation_last_checked_at != initial_last_checked

    def test_register_creates_user_product_list_entries_for_single_product_intent(self):
        ProductIntent.register(
            self.team, ProductKey.SESSION_REPLAY, ProductIntentContext.SESSION_REPLAY_SET_FILTERS, self.user
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 1

        upl = user_product_lists.get()
        assert upl.product_path == "Session replay"
        assert upl.enabled is True
        assert upl.reason == UserProductList.Reason.PRODUCT_INTENT

    def test_register_creates_user_product_list_entries_for_multiple_product_intent(self):
        ProductIntent.register(
            self.team, ProductKey.DATA_WAREHOUSE, ProductIntentContext.DATA_WAREHOUSE_SOURCES_TABLE, self.user
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team).order_by("product_path")
        assert user_product_lists.count() == 2

        product_paths = {upl.product_path for upl in user_product_lists}
        assert product_paths == {"Data warehouse", "SQL editor"}

        enabled = [upl.enabled for upl in user_product_lists]
        assert all(enabled)

        reasons = [upl.reason for upl in user_product_lists]
        assert all(reason == UserProductList.Reason.PRODUCT_INTENT for reason in reasons)

    def test_register_ignores_product_key_without_products(self):
        ProductIntent.register(
            self.team, ProductKey.ANNOTATIONS, ProductIntentContext.DATA_WAREHOUSE_SOURCES_TABLE, self.user
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 0

    def test_register_respects_allow_sidebar_suggestions_false(self):
        self.user.allow_sidebar_suggestions = False
        self.user.save()

        ProductIntent.register(
            self.team, ProductKey.DATA_WAREHOUSE, ProductIntentContext.DATA_WAREHOUSE_SOURCES_TABLE, self.user
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 0

    def test_register_does_not_create_duplicates_on_multiple_calls(self):
        assert UserProductList.objects.filter(user=self.user, team=self.team).count() == 0

        ProductIntent.register(
            self.team, ProductKey.SESSION_REPLAY, ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY, self.user
        )
        assert UserProductList.objects.filter(user=self.user, team=self.team).count() == 1

        ProductIntent.register(
            self.team, ProductKey.SESSION_REPLAY, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )
        assert UserProductList.objects.filter(user=self.user, team=self.team).count() == 1

    def test_register_creates_user_product_list_for_different_intents(self):
        ProductIntent.register(
            self.team, ProductKey.SESSION_REPLAY, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )
        assert UserProductList.objects.filter(user=self.user, team=self.team).count() == 1

        ProductIntent.register(
            self.team, ProductKey.PRODUCT_ANALYTICS, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )
        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 3

        product_paths = {upl.product_path for upl in user_product_lists}
        assert product_paths == {"Session replay", "Dashboards", "Product analytics"}

    def test_register_allows_creation_when_allow_sidebar_suggestions_is_none(self):
        self.user.allow_sidebar_suggestions = None
        self.user.save()

        ProductIntent.register(
            self.team, ProductKey.SURVEYS, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 1
        assert user_product_lists.get().product_path == "Surveys"

    def test_register_allows_creation_when_allow_sidebar_suggestions_is_true(self):
        self.user.allow_sidebar_suggestions = True
        self.user.save()

        ProductIntent.register(
            self.team, ProductKey.SURVEYS, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 1
        assert user_product_lists.get().product_path == "Surveys"

    def test_register_rejects_creation_when_allow_sidebar_suggestions_is_false(self):
        self.user.allow_sidebar_suggestions = False
        self.user.save()

        ProductIntent.register(
            self.team, ProductKey.SURVEYS, ProductIntentContext.QUICK_START_PRODUCT_SELECTED, self.user
        )
        assert UserProductList.objects.filter(user=self.user, team=self.team).count() == 0

    def test_register_with_onboarding_context_creates_user_product_list_with_onboarding_reason(self):
        self.user.allow_sidebar_suggestions = True
        self.user.save()

        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.SESSION_REPLAY,
            context=ProductIntentContext.ONBOARDING_PRODUCT_SELECTED___PRIMARY,
            user=self.user,
            is_onboarding=True,
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 1
        assert user_product_lists.get().reason == UserProductList.Reason.ONBOARDING

    def test_register_with_quick_start_context_creates_user_product_list_with_onboarding_reason(self):
        self.user.allow_sidebar_suggestions = True
        self.user.save()

        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.SESSION_REPLAY,
            context=ProductIntentContext.QUICK_START_PRODUCT_SELECTED,
            user=self.user,
            is_onboarding=True,
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 1
        assert user_product_lists.get().reason == UserProductList.Reason.ONBOARDING

    def test_register_without_onboarding_context_creates_user_product_list_with_product_intent_reason(self):
        self.user.allow_sidebar_suggestions = True
        self.user.save()

        ProductIntent.register(
            team=self.team,
            product_type=ProductKey.SESSION_REPLAY,
            context=ProductIntentContext.SESSION_REPLAY_SET_FILTERS,
            user=self.user,
            is_onboarding=False,
        )

        user_product_lists = UserProductList.objects.filter(user=self.user, team=self.team)
        assert user_product_lists.count() == 1
        assert user_product_lists.get().reason == UserProductList.Reason.PRODUCT_INTENT
