import requests
from urllib.parse import urlparse
from unittest.mock import Mock, patch
from freezegun import freeze_time

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.models import PersonalAPIKey, Team
from posthog.models.utils import generate_random_token_personal
from posthog.models.personal_api_key import hash_key_value
from posthog.models.web_preaggregated.team_selection_strategies import FeatureEnrollmentStrategy


class BaseFeatureEnrollmentTest:
    def setup_method(self):
        self.mock_context = Mock()
        self.mock_context.log = Mock()

    def create_strategy(
        self,
        api_host: str = "https://test-api.posthog.com",
        api_token: str | None = "test-token",
        flag_key: str = "test-flag",
    ) -> FeatureEnrollmentStrategy:
        return FeatureEnrollmentStrategy(api_host=api_host, api_token=api_token, flag_key=flag_key)

    def create_mock_response(self, status_code: int = 200, results: list | None = None, **response_data) -> Mock:
        mock_response = Mock()
        mock_response.status_code = status_code
        mock_response.text = response_data.get("text", f"HTTP {status_code} response")

        if status_code == 200:
            response_json = {"results": results or []}
            response_json.update(response_data)
            mock_response.json.return_value = response_json

        return mock_response

    def assert_api_call_structure(self, mock_post, expected_host: str, expected_team_id: int = 2):
        mock_post.assert_called_once()
        call_args = mock_post.call_args

        # Check URL structure
        url = call_args[0][0] if call_args[0] else call_args[1]["url"]
        assert expected_host in url
        assert f"/api/environments/{expected_team_id}/query/" in url

        # Check basic headers
        headers = call_args[1]["headers"]
        assert "Authorization" in headers
        assert headers["Content-Type"] == "application/json"

        # Check timeout
        assert call_args[1]["timeout"] == 30

        return call_args[1]["json"]  # Return query payload for further assertions


class TestFeatureEnrollmentStrategyUnit(BaseFeatureEnrollmentTest):
    def test_returns_empty_set_when_no_api_token(self):
        strategy = self.create_strategy(api_token=None)
        result = strategy.get_teams(self.mock_context)

        assert result == set()
        self.mock_context.log.error.assert_called_with(
            "WEB_ANALYTICS_FEATURE_ENROLLMENT_API_TOKEN not configured, cannot fetch feature enrollment data"
        )

    @patch("posthog.models.web_preaggregated.team_selection_strategies.is_cloud", return_value=False)
    def test_returns_empty_set_for_self_hosted(self, mock_is_cloud):
        strategy = self.create_strategy()
        result = strategy.get_teams(self.mock_context)

        assert result == set()
        self.mock_context.log.warning.assert_called_with(
            "Skipping feature enrollment strategy for self-hosted instances. This strategy is only available on posthog cloud."
        )

    @patch("posthog.models.web_preaggregated.team_selection_strategies.is_cloud", return_value=True)
    def test_region_host_detection(self, mock_is_cloud):
        strategy = self.create_strategy()

        test_cases = [
            ("https://us.posthog.com", "us.posthog.com"),
            ("https://eu.posthog.com", "eu.posthog.com"),
            ("https://app.posthog.com", "app.posthog.com"),
            ("https://localhost:8000", "localhost:8000"),
        ]

        for site_url, expected_host in test_cases:
            with patch("posthog.models.web_preaggregated.team_selection_strategies.settings.SITE_URL", site_url):
                assert strategy._get_region_host() == expected_host


class TestFeatureEnrollmentStrategyMocked(BaseFeatureEnrollmentTest):
    @patch("posthog.models.web_preaggregated.team_selection_strategies.is_cloud", return_value=True)
    @patch("requests.post")
    def test_successful_api_call_with_results(self, mock_post, mock_is_cloud):
        # Setup
        strategy = self.create_strategy(flag_key="custom-flag")
        mock_response = self.create_mock_response(results=[["123", "us.posthog.com"], ["456", "us.posthog.com"]])
        mock_post.return_value = mock_response

        with patch(
            "posthog.models.web_preaggregated.team_selection_strategies.settings.SITE_URL", "https://us.posthog.com"
        ):
            # Execute
            result = strategy.get_teams(self.mock_context)

        # Assert
        assert result == {123, 456}

        query_payload = self.assert_api_call_structure(mock_post, "https://test-api.posthog.com")
        query = query_payload["query"]["query"]
        assert "custom-flag" in query
        assert "properties.$host = 'us.posthog.com'" in query
        assert "event = '$feature_enrollment_update'" in query

    @patch("posthog.models.web_preaggregated.team_selection_strategies.is_cloud", return_value=True)
    @patch("requests.post")
    def test_api_response_data_validation(self, mock_post, mock_is_cloud):
        strategy = self.create_strategy()
        mock_response = self.create_mock_response(
            results=[
                ["123", "us.posthog.com"],  # Valid
                ["456", "us.posthog.com"],  # Valid
                [None, "us.posthog.com"],  # Invalid - None
                ["", "us.posthog.com"],  # Invalid - empty string
                ["invalid", "us.posthog.com"],  # Invalid - non-numeric
                ["789", "us.posthog.com"],  # Valid
            ]
        )
        mock_post.return_value = mock_response

        result = strategy.get_teams(self.mock_context)
        assert result == {123, 456, 789}

    @patch("posthog.models.web_preaggregated.team_selection_strategies.is_cloud", return_value=True)
    @patch("requests.post")
    def test_api_error_handling(self, mock_post, mock_is_cloud):
        strategy = self.create_strategy()

        # Test network error
        mock_post.side_effect = requests.RequestException("Network timeout")
        result = strategy.get_teams(self.mock_context)
        assert result == set()

        # Test HTTP error
        mock_post.side_effect = None
        mock_post.return_value = self.create_mock_response(status_code=403, text="Forbidden")
        result = strategy.get_teams(self.mock_context)
        assert result == set()

        # Test malformed response
        mock_response = self.create_mock_response(status_code=200)
        mock_response.json.return_value = {"unexpected": "format"}
        mock_post.return_value = mock_response
        result = strategy.get_teams(self.mock_context)
        assert result == set()


class TestFeatureEnrollmentStrategyAPIIntegration(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        self.mock_context = Mock()
        self.mock_context.log = Mock()

        self.another_team = Team.objects.create(organization=self.organization, name="Another team who is interested")

    def create_feature_enrollment_events(self):
        with freeze_time("2024-01-10 12:00:00"):
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

            _create_event(
                team=self.team,
                event="$feature_enrollment_update",
                distinct_id="user2",
                properties={
                    "$feature_flag": "web-analytics-api",
                    "$host": "localhost:8000",
                    "$current_url": f"https://localhost:8000/project/{self.another_team.pk}/dashboard",  # The URL is configured for that other team usage
                },
            )

        flush_persons_and_events()

    # Patch requests.post to use Django test client but
    def _redirect_request_to_test_api(self, url, json=None, headers=None, timeout=None):
        parsed_url = urlparse(url)
        path = parsed_url.path

        # Use Django test client to "redirect" the request to our internal api
        response = self.client.post(path, json)

        # Shape the result as request expects it
        mock_response = Mock()
        mock_response.status_code = response.status_code
        mock_response.json.return_value = response.json()
        mock_response.text = response.content.decode()
        return mock_response

    def test_strategy_with_full_integration(self):
        """
        Comprehensive integration test that verifies the FeatureEnrollmentStrategy
        can correctly identify teams with enrolled users through the actual API.

        This test:
        1. Creates enrollment events for multiple teams (self.team and self.another_team)
        2. Uses a real PersonalAPIKey with the local API endpoint
        3. Calls FeatureEnrollmentStrategy.get_teams() method
        4. Verifies the strategy returns the correct set of team IDs
        """
        self.create_feature_enrollment_events()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Strategy API Key", user=self.user, secure_value=hash_key_value(personal_api_key)
        )

        with freeze_time("2024-01-10 12:30:00"):
            strategy = FeatureEnrollmentStrategy(
                api_host=f"http://testserver",
                api_token=personal_api_key,
                flag_key="web-analytics-api",
                since_date="2024-01-01",
                team_id=self.team.id,
            )

            with patch("posthog.models.web_preaggregated.team_selection_strategies.is_cloud", return_value=True):
                with patch(
                    "posthog.models.web_preaggregated.team_selection_strategies.settings.SITE_URL",
                    "https://localhost:8000",
                ):
                    with patch(
                        "posthog.models.web_preaggregated.team_selection_strategies.requests.post",
                        side_effect=self._redirect_request_to_test_api,
                    ):
                        result = strategy.get_teams(self.mock_context)

            assert result == {self.team.pk, self.another_team.pk}
