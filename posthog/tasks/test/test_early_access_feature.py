from unittest.mock import patch, MagicMock
from posthog.models.team import Team
from posthog.models.person.person import Person
from posthog.models.feature_flag.feature_flag import FeatureFlag
from products.early_access_features.backend.models import EarlyAccessFeature
from posthog.tasks.early_access_feature import send_events_for_early_access_feature_stage_change
from posthog.test.base import APIBaseTest


class TestSendEventsForEarlyAccessFeatureStageChange(APIBaseTest):
    @patch("posthoganalytics.capture")
    def test_sends_event_for_enrolled_users(self, mock_capture: MagicMock) -> None:
        team = Team.objects.create(organization=self.organization)
        feature_flag = FeatureFlag.objects.create(team=team, key="my-flag", filters={})
        feature = EarlyAccessFeature.objects.create(
            team=team,
            feature_flag=feature_flag,
            name="Test Feature",
            description="desc",
            stage=EarlyAccessFeature.Stage.BETA,
        )

        Person.objects.create(
            team=team,
            distinct_ids=["abc123"],
            properties={f"$feature_enrollment/{feature_flag.key}": True, "email": "test@example.com"},
        )

        send_events_for_early_access_feature_stage_change(str(feature.id), str(feature.team.id), "concept", "beta")

        mock_capture.assert_called_once_with(
            "abc123",
            "user moved feature preview stage",
            {
                "from": "concept",
                "to": "beta",
                "feature_flag_key": feature_flag.key,
                "feature_id": feature.id,
                "feature_name": "Test Feature",
                "user_email": "test@example.com",
            },
        )

    @patch("posthoganalytics.capture")
    def test_no_event_for_enrolled_users_on_different_team(self, mock_capture: MagicMock) -> None:
        team1 = Team.objects.create(organization=self.organization)
        team2 = Team.objects.create(organization=self.organization)
        feature_flag = FeatureFlag.objects.create(team=team1, key="my-flag", filters={})
        feature = EarlyAccessFeature.objects.create(
            team=team1,
            feature_flag=feature_flag,
            name="Test Feature",
            description="desc",
            stage=EarlyAccessFeature.Stage.BETA,
        )

        # Person on a different team, but with the same feature flag key
        Person.objects.create(
            team=team2,
            distinct_ids=["other123"],
            properties={f"$feature_enrollment/{feature_flag.key}": True, "email": "other@example.com"},
        )

        send_events_for_early_access_feature_stage_change(str(feature.id), str(feature.team.id), "concept", "beta")

        mock_capture.assert_not_called()
