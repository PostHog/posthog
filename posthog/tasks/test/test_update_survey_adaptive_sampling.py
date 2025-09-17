import json
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import FeatureFlag, Survey
from posthog.tasks.update_survey_adaptive_sampling import update_survey_adaptive_sampling


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
            rollout_percentage=100,
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
        self.assertEqual(internal_response_sampling_flag.rollout_percentage, 20)
        mock_get_count.assert_called_once_with(self.survey.id)

    @freeze_time("2024-12-21T12:00:00Z")
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_updates_rollout_after_interval_is_over(self, mock_get_count: MagicMock) -> None:
        mock_get_count.return_value = 50
        update_survey_adaptive_sampling()
        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.rollout_percentage, 100)
        mock_get_count.assert_called_once_with(self.survey.id)
        survey = Survey.objects.get(id=self.survey.id)
        response_sampling_daily_limits = json.loads(survey.response_sampling_daily_limits)
        self.assertEqual(response_sampling_daily_limits[0].get("date"), "2024-12-22")

    @freeze_time("2024-12-13T12:00:00Z")
    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_no_update_when_limit_reached(self, mock_get_count: MagicMock) -> None:
        mock_get_count.return_value = 100
        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.rollout_percentage, 100)
        mock_get_count.assert_called_once_with(self.survey.id)

    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_ignores_ended_surveys(self, mock_get_count: MagicMock) -> None:
        self.survey.end_date = timezone.now()
        self.survey.response_sampling_daily_limits = [
            {"date": timezone.now().date().isoformat(), "daily_response_limit": 100, "rollout_percentage": 50}
        ]
        self.survey.save()

        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.rollout_percentage, 100)
        mock_get_count.assert_not_called()

    @patch("posthog.tasks.update_survey_adaptive_sampling._get_survey_responses_count")
    def test_ignores_surveys_without_limits(self, mock_get_count: MagicMock) -> None:
        self.survey.response_sampling_limit = 0
        self.survey.save()

        update_survey_adaptive_sampling()

        internal_response_sampling_flag = FeatureFlag.objects.get(id=self.internal_response_sampling_flag.id)
        self.assertEqual(internal_response_sampling_flag.rollout_percentage, 100)
        mock_get_count.assert_not_called()
