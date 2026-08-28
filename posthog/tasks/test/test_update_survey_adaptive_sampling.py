import json
from copy import deepcopy
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.tasks.update_survey_adaptive_sampling import update_survey_adaptive_sampling

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.surveys.backend.models import Survey


class TestUpdateSurveyAdaptiveSampling(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.survey = Survey.objects.create(
            team=self.team,
            name="Test survey",
            type="popover",
            start_date=timezone.now(),
            response_sampling_start_date=datetime(2024, 12, 12),
            response_sampling_limit=500,
            response_sampling_interval=10,
            response_sampling_interval_type="day",
        )
        self.internal_response_sampling_flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"survey-targeting-{self.survey.id}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        self.survey.internal_response_sampling_flag = self.internal_response_sampling_flag
        self.survey.save()

    @freeze_time("2024-12-13T12:00:00Z")
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_updates_rollout(self, mock_get_count: MagicMock) -> None:
        mock_get_count.return_value = 50
        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"], 20)
        mock_get_count.assert_called_once_with(self.survey)

    @freeze_time("2024-12-21T12:00:00Z")
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_updates_rollout_after_interval_is_over(self, mock_get_count: MagicMock) -> None:
        mock_get_count.return_value = 50
        update_survey_adaptive_sampling()
        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"], 100)
        mock_get_count.assert_called_once_with(self.survey)
        survey = Survey.objects.get(id=self.survey.id)
        assert survey.response_sampling_daily_limits is not None
        response_sampling_daily_limits = json.loads(survey.response_sampling_daily_limits)
        self.assertEqual(response_sampling_daily_limits[0].get("date"), "2024-12-22")

    @freeze_time("2024-12-13T12:00:00Z")
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_no_update_when_limit_reached(self, mock_get_count: MagicMock) -> None:
        mock_get_count.return_value = 100
        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"], 100)
        mock_get_count.assert_called_once_with(self.survey)

    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_ignores_ended_surveys(self, mock_get_count: MagicMock) -> None:
        self.survey.end_date = timezone.now()
        self.survey.response_sampling_daily_limits = [
            {"date": timezone.now().date().isoformat(), "daily_response_limit": 100, "rollout_percentage": 50}
        ]
        self.survey.save()

        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"], 100)
        mock_get_count.assert_not_called()

    @parameterized.expand(
        [
            (
                "sampling_flag_shape",
                {"groups": [{"variant": "", "rollout_percentage": 100, "properties": []}]},
            ),
            (
                "targeting_shape_with_internal_properties",
                {
                    "groups": [
                        {
                            "variant": "",
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "$survey_dismissed/0192e-abc",
                                    "value": "is_not_set",
                                    "operator": "is_not_set",
                                    "type": "person",
                                },
                                {
                                    "key": "$survey_responded/0192e-abc",
                                    "value": "is_not_set",
                                    "operator": "is_not_set",
                                    "type": "person",
                                },
                                {
                                    "key": "$survey_last_seen_date",
                                    "value": "30d",
                                    "operator": "is_date_before",
                                    "type": "person",
                                },
                            ],
                        },
                        {"variant": "", "rollout_percentage": 100, "properties": []},
                    ]
                },
            ),
        ]
    )
    @freeze_time("2024-12-13T12:00:00Z")
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_round_trip_preserves_filters_except_rollout(
        self, _name: str, filters: dict, mock_get_count: MagicMock
    ) -> None:
        self.internal_response_sampling_flag.filters = filters
        self.internal_response_sampling_flag.save()
        expected = deepcopy(filters)
        expected["groups"][0]["rollout_percentage"] = 20
        # The serializer normalizes aggregation onto every condition set (None = person-aggregated)
        for group in expected["groups"]:
            group["aggregation_group_type_index"] = None
        expected["aggregation_group_type_index"] = None

        mock_get_count.return_value = 50
        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters, expected)

    @freeze_time("2024-12-13T12:00:00Z")
    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_system_write_skips_approval_gate_and_logs_system_activity(
        self, mock_get_count: MagicMock, _mock_enabled: MagicMock
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        mock_get_count.return_value = 50

        with self.captureOnCommitCallbacks(execute=True):
            update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"], 20)
        self.assertFalse(ChangeRequest.objects.filter(team=self.team).exists())
        log = ActivityLog.objects.get(
            scope="FeatureFlag", item_id=str(internal_response_sampling_flag.id), activity="updated"
        )
        self.assertTrue(log.is_system)
        self.assertIsNone(log.user)

    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_ignores_surveys_without_limits(self, mock_get_count: MagicMock) -> None:
        self.survey.response_sampling_limit = 0
        self.survey.save()

        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.filters["groups"][0]["rollout_percentage"], 100)
        mock_get_count.assert_not_called()
