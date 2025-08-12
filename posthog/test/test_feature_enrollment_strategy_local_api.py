from unittest.mock import Mock, patch
from freezegun import freeze_time

from dags.web_preaggregated_team_selection_strategies import FeatureEnrollmentStrategy
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.models import PersonalAPIKey, Team
from posthog.models.utils import generate_random_token_personal
from posthog.models.personal_api_key import hash_key_value


class TestFeatureEnrollmentStrategyLocalAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        self.mock_context = Mock()
        self.mock_context.log = Mock()

        # Create additional test team for multi-team scenarios
        self.team2 = Team.objects.create(organization=self.organization, name="Test Team 2")

    def create_feature_enrollment_events(self):
        with freeze_time("2024-01-10 12:00:00"):
            # Event for team 1 with web-analytics-api flag
            _create_event(
                team=self.team,
                event="$feature_enrollment_update",
                distinct_id="user1",
                properties={
                    "$feature_flag": "web-analytics-api",
                    "$host": "localhost:8000",
                    "$current_url": f"https://localhost:8000/project/{self.team.pk}/insights",
                },
            )

            # Event for team 2 with web-analytics-api flag
            _create_event(
                team=self.team,
                event="$feature_enrollment_update",
                distinct_id="user2",
                properties={
                    "$feature_flag": "web-analytics-api",
                    "$host": "localhost:8000",
                    "$current_url": f"https://localhost:8000/project/{self.team2.pk}/dashboard",
                },
            )

        flush_persons_and_events()

    def test_direct_api_query_finds_enrolled_teams(self):
        self.create_feature_enrollment_events()

        with freeze_time("2024-01-10 12:30:00"):
            query = {
                "kind": "HogQLQuery",
                "query": """
                    SELECT DISTINCT
                        extract(properties.$current_url, '/project/([0-9]+)/') as project_id,
                        properties.$host
                    FROM events
                    WHERE event = '$feature_enrollment_update'
                        AND properties.$host = 'localhost:8000'
                        AND timestamp >= '2024-01-01'
                        AND properties.$feature_flag = 'web-analytics-api'
                """,
            }

            response = self.client.post(f"/api/environments/{self.team.id}/query/", {"query": query})
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertIn("results", data)
            results = data["results"]

            # Should find both teams that enrolled in web-analytics-api on localhost:8000
            team_ids = {int(row[0]) for row in results if row[0]}
            self.assertIn(self.team.pk, team_ids)
            self.assertIn(self.team2.pk, team_ids)

            # Verify host filtering worked
            hosts = {row[1] for row in results}
            self.assertEqual(hosts, {"localhost:8000"})

    def test_strategy_with_local_api_integration(self):
        self.create_feature_enrollment_events()

        # Create personal API token for the strategy
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Strategy API Key", user=self.user, secure_value=hash_key_value(personal_api_key)
        )

        with freeze_time("2024-01-10 12:30:00"):
            strategy = FeatureEnrollmentStrategy(
                api_host=f"http://localhost:8000", api_token=personal_api_key, flag_key="web-analytics-api"
            )

            with patch("dags.web_preaggregated_team_selection_strategies.is_cloud", return_value=True):
                with patch(
                    "dags.web_preaggregated_team_selection_strategies.settings.SITE_URL", "https://localhost:8000"
                ):
                    result = strategy.get_teams(self.mock_context)

            self.assertIsInstance(result, set)

            # Verify API call was attempted
            info_calls = [str(call) for call in self.mock_context.log.info.call_args_list]
            self.assertTrue(any("Querying PostHog internal API" in call for call in info_calls))
