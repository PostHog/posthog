from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql.constants import DEFAULT_RETURNED_ROWS

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.person.person import Person
from posthog.models.team import Team
from posthog.tasks.early_access_feature import send_events_for_early_access_feature_stage_change

from products.early_access_features.backend.models import EarlyAccessFeature


class TestSendEventsForEarlyAccessFeatureStageChange(APIBaseTest):
    @patch("posthog.tasks.early_access_feature.get_client")
    def test_sends_event_for_enrolled_users(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

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

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        mock_client.capture.assert_called_once_with(
            "abc123",
            "user moved feature preview stage",
            properties={
                "from": "concept",
                "to": "beta",
                "feature_flag_key": feature_flag.key,
                "feature_id": feature.id,
                "feature_name": "Test Feature",
                "user_email": "test@example.com",
            },
        )

        mock_client.shutdown.assert_called_once()

    @patch("posthog.tasks.early_access_feature.get_client")
    def test_no_event_for_enrolled_users_on_different_team(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

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

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        mock_client.capture.assert_not_called()

    @patch("posthog.tasks.early_access_feature.get_client")
    def test_sends_events_for_all_enrolled_users_over_default_hogql_limit(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        team = Team.objects.create(organization=self.organization)
        feature_flag = FeatureFlag.objects.create(team=team, key="test-limit-flag", filters={})
        feature = EarlyAccessFeature.objects.create(
            team=team,
            feature_flag=feature_flag,
            name="Test Feature",
            description="desc",
            stage=EarlyAccessFeature.Stage.BETA,
        )

        persons_count = DEFAULT_RETURNED_ROWS + 10  # create more than the default limit, to check they aren't truncated

        persons = []
        for i in range(persons_count):
            person = Person.objects.create(
                team=team,
                distinct_ids=[f"user_{i}"],
                properties={f"$feature_enrollment/{feature_flag.key}": True, "email": f"user_{i}@example.com"},
            )
            persons.append(person)

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        assert mock_client.capture.call_count == persons_count

        for i in range(persons_count):
            mock_client.capture.assert_any_call(
                f"user_{i}",
                "user moved feature preview stage",
                properties={
                    "from": "concept",
                    "to": "beta",
                    "feature_flag_key": feature_flag.key,
                    "feature_id": feature.id,
                    "feature_name": "Test Feature",
                    "user_email": f"user_{i}@example.com",
                },
            )
