from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql.constants import DEFAULT_RETURNED_ROWS

from posthog.models.team import Team
from posthog.tasks.early_access_feature import send_events_for_early_access_feature_stage_change
from posthog.test.persons import add_distinct_id, create_person

from products.early_access_features.backend.models import EarlyAccessFeature
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestSendEventsForEarlyAccessFeatureStageChange(APIBaseTest):
    @patch("posthog.tasks.early_access_feature.capture_event")
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

        create_person(
            team=team,
            distinct_ids=["abc123"],
            properties={f"$feature_enrollment/{feature_flag.key}": True, "email": "test@example.com"},
        )

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        mock_capture.assert_called_once_with(
            "user moved feature preview stage",
            distinct_id="abc123",
            properties={
                "from": "concept",
                "to": "beta",
                "feature_flag_key": feature_flag.key,
                "feature_id": feature.id,
                "feature_name": "Test Feature",
                "user_email": "test@example.com",
            },
        )

    @patch("posthog.tasks.early_access_feature.capture_event")
    def test_sends_one_event_for_person_with_multiple_distinct_ids(self, mock_capture: MagicMock) -> None:
        team = Team.objects.create(organization=self.organization)
        feature_flag = FeatureFlag.objects.create(team=team, key="my-flag", filters={})
        feature = EarlyAccessFeature.objects.create(
            team=team,
            feature_flag=feature_flag,
            name="Test Feature",
            description="desc",
            stage=EarlyAccessFeature.Stage.BETA,
        )

        create_person(
            team=team,
            distinct_ids=["anon123", "abc123"],
            properties={f"$feature_enrollment/{feature_flag.key}": True, "email": "test@example.com"},
        )

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        mock_capture.assert_called_once()
        assert mock_capture.call_args.kwargs["distinct_id"] in {"anon123", "abc123"}
        assert mock_capture.call_args.kwargs["properties"]["user_email"] == "test@example.com"

    @patch("posthog.tasks.early_access_feature.capture_event")
    def test_skips_distinct_id_reassigned_to_another_person(self, mock_capture: MagicMock) -> None:
        team = Team.objects.create(organization=self.organization)
        feature_flag = FeatureFlag.objects.create(team=team, key="my-flag", filters={})
        feature = EarlyAccessFeature.objects.create(
            team=team,
            feature_flag=feature_flag,
            name="Test Feature",
            description="desc",
            stage=EarlyAccessFeature.Stage.BETA,
        )

        enrolled = create_person(
            team=team,
            distinct_ids=["enrolled_id"],
            properties={f"$feature_enrollment/{feature_flag.key}": True, "email": "test@example.com"},
        )
        add_distinct_id(person=enrolled, distinct_id="moved_id", version=1)
        other = create_person(team=team, distinct_ids=["other_id"], properties={})
        # A merge reassigns moved_id to the other person with a higher version; the old
        # mapping row stays in raw_person_distinct_ids.
        add_distinct_id(person=other, distinct_id="moved_id", version=2)

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        mock_capture.assert_called_once()
        assert mock_capture.call_args.kwargs["distinct_id"] == "enrolled_id"
        assert mock_capture.call_args.kwargs["properties"]["user_email"] == "test@example.com"

    @patch("posthog.tasks.early_access_feature.capture_event")
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
        create_person(
            team=team2,
            distinct_ids=["other123"],
            properties={f"$feature_enrollment/{feature_flag.key}": True, "email": "other@example.com"},
        )

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        mock_capture.assert_not_called()

    @patch("posthog.tasks.early_access_feature.capture_event")
    def test_sends_events_for_all_enrolled_users_over_default_hogql_limit(self, mock_capture: MagicMock) -> None:
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
            person = create_person(
                team=team,
                distinct_ids=[f"user_{i}"],
                properties={f"$feature_enrollment/{feature_flag.key}": True, "email": f"user_{i}@example.com"},
            )
            persons.append(person)

        send_events_for_early_access_feature_stage_change(feature.id, "concept", "beta")

        assert mock_capture.call_count == persons_count

        for i in range(persons_count):
            mock_capture.assert_any_call(
                "user moved feature preview stage",
                distinct_id=f"user_{i}",
                properties={
                    "from": "concept",
                    "to": "beta",
                    "feature_flag_key": feature_flag.key,
                    "feature_id": feature.id,
                    "feature_name": "Test Feature",
                    "user_email": f"user_{i}@example.com",
                },
            )
