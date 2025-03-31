from posthog.schema import SDKDeprecationWarningsResponse, Level
from posthog.test.base import ClickhouseTestMixin, APIBaseTest, QueryMatchingTest, _create_event
from freezegun import freeze_time
import responses
from datetime import datetime, timedelta
from unittest.mock import patch

from rest_framework import status

@freeze_time("2025-01-01T12:00:00Z")
class TestSdkDeprecationWarningsAPi(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_empty_response(self):
        response = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )
        assert response.status_code == status.HTTP_200_OK
        response_body = SDKDeprecationWarningsResponse(**response.json())
        assert len(response_body.warnings) == 0

    @responses.activate
    def test_sdk_with_deprecation_warning(self):
        # Set up tag responses
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-js/tags",
            json=[
                {"name": "1.5.0"},
                {"name": "1.4.0"},
                {"name": "1.3.0"},
                {"name": "1.2.0"},
                {"name": "1.1.0"},
                {"name": "1.0.0"},
            ],
            status=200,
        )

        # Set up deprecation response
        responses.add(
            responses.GET,
            "https://raw.githubusercontent.com/PostHog/posthog-js/main/deprecation.json",
            json={"deprecateBeforeVersion": "1.3.0"},
            status=200,
        )

        # Create events with deprecated version
        self._create_events_with_sdk("web", "1.0.0")

        response = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        assert response.status_code == status.HTTP_200_OK
        response_body = SDKDeprecationWarningsResponse(**response.json())

        # Check that we have a deprecation warning
        assert len(response_body.warnings) == 1
        warning = response_body.warnings[0]

        assert warning.lib == "web"
        assert warning.latestUsedVersion == "1.0.0"
        assert warning.level == Level.WARNING
        assert "deprecated" in warning.message
        assert "1.3.0" in warning.message

    @responses.activate
    def test_sdk_with_version_behind_warning(self):
        # Set up tag responses
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-python/tags",
            json=[{"name": "v2.0.0"}] + [{"name": f"v1.{i}.0"} for i in range(60, 0, -1)],
            status=200,
        )

        # Create events with outdated version
        self._create_events_with_sdk("posthog-python", "1.10.0")

        response = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        assert response.status_code == status.HTTP_200_OK
        response_body = SDKDeprecationWarningsResponse(**response.json())

        # Check that we have a version behind warning
        assert len(response_body.warnings) == 1
        warning = response_body.warnings[0]

        assert warning.lib == "posthog-python"
        assert warning.latestUsedVersion == "1.10.0"
        assert warning.latestAvailableVersion == "2.0.0"
        assert warning.level == Level.ERROR  # 51 versions behind (2.0.0 vs 1.10.0) should be error
        assert warning.numVersionsBehind >= 50

    @responses.activate
    def test_multiple_sdk_warnings(self):
        # Set up tag responses for web
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-js/tags",
            json=[
                {"name": "1.5.0"},
                {"name": "1.4.0"},
                {"name": "1.3.0"},
            ],
            status=200,
        )

        # Set up deprecation response for web
        responses.add(
            responses.GET,
            "https://raw.githubusercontent.com/PostHog/posthog-js/main/deprecation.json",
            json={"deprecateBeforeVersion": "1.3.0"},
            status=200,
        )

        # Set up tag responses for python
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-python/tags",
            json=[{"name": "v2.0.0"}] + [{"name": f"v1.{i}.0"} for i in range(60, 0, -1)],
            status=200,
        )

        # Create events with multiple SDKs
        self._create_events_with_sdk("web", "1.2.0")
        self._create_events_with_sdk("posthog-python", "1.10.0")

        response = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        assert response.status_code == status.HTTP_200_OK
        response_body = SDKDeprecationWarningsResponse(**response.json())

        # Check that we have both warnings
        assert len(response_body.warnings) == 2

        # Check for web warning
        web_warning = next((w for w in response_body.warnings if w.lib == "web"), None)
        assert web_warning is not None
        assert web_warning.latestUsedVersion == "1.2.0"
        assert web_warning.level == Level.WARNING
        assert "deprecated" in web_warning.message

        # Check for python warning
        python_warning = next((w for w in response_body.warnings if w.lib == "posthog-python"), None)
        assert python_warning is not None
        assert python_warning.latestUsedVersion == "1.10.0"
        assert python_warning.latestAvailableVersion == "2.0.0"
        assert python_warning.level == Level.ERROR

    @responses.activate
    def test_no_warning_for_up_to_date_sdk(self):
        # Set up tag responses
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-js/tags",
            json=[
                {"name": "1.5.0"},
                {"name": "1.4.0"},
                {"name": "1.3.0"},
                {"name": "1.2.0"},
            ],
            status=200,
        )

        # Create events with up-to-date version
        self._create_events_with_sdk("web", "1.5.0")

        response = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        assert response.status_code == status.HTTP_200_OK
        response_body = SDKDeprecationWarningsResponse(**response.json())

        # Check that there are no warnings
        assert len(response_body.warnings) == 0

    @responses.activate
    def test_caching_of_tags_and_deprecation(self):
        # Set up initial tag responses
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-js/tags",
            json=[
                {"name": "1.5.0"},
                {"name": "1.4.0"},
            ],
            status=200,
        )

        # Create events with SDK
        self._create_events_with_sdk("web", "1.3.0")

        # First request should hit the GitHub API
        response1 = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        # Change the API response
        responses.reset()
        responses.add(
            responses.GET,
            "https://api.github.com/repos/posthog/posthog-js/tags",
            json=[
                {"name": "2.0.0"},  # New version available
                {"name": "1.5.0"},
                {"name": "1.4.0"},
            ],
            status=200,
        )

        # Second request should use cached data
        response2 = self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        # Both responses should have the same data
        assert response1.json() == response2.json()

    @patch('posthog.api.sdk_deprecation_warnings.redis.get_client')
    def test_cached_usage_with_different_ttls(self, mock_redis):
        # Create a mock Redis client
        mock_client = mock_redis.return_value
        mock_client.get.return_value = None  # No cache hits initially

        # Create events with SDK
        self._create_events_with_sdk("web", "1.0.0")

        # Make request to trigger caching
        self.client.get(
            f"/api/projects/{self.team.id}/sdk_deprecation_warnings/warnings",
            data={},
            HTTP_ORIGIN="http://testserver",
        )

        # Check that caching was done with correct TTLs
        today_isoformat = datetime(2025, 1, 1).date().isoformat()
        yesterday_isoformat = (datetime(2025, 1, 1) - timedelta(days=1)).date().isoformat()

        # Find the calls for current day and previous day
        today_calls = [
            call for call in mock_client.set.call_args_list
            if f"{self.team.id}:{today_isoformat}" in call[0][0]
        ]
        previous_day_calls = [
            call for call in mock_client.set.call_args_list
            if f"{self.team.id}:{yesterday_isoformat}" in call[0][0]
        ]

        # Check that we have the expected calls
        assert len(today_calls) > 0
        assert len(previous_day_calls) > 0

        # Check TTLs
        for call in today_calls:
            assert call[1].get('ex') == 60 * 60  # 1 hour for today

        for call in previous_day_calls:
            assert call[1].get('ex') == 7 * 24 * 60 * 60  # 7 days for historical

    def _create_events_with_sdk(self, lib, version):
        # Get the date range for the past week
        self._create_events_for_dates(lib, version, [
            datetime(2025, 1, 1) - timedelta(days=i) for i in range(7)
        ])

    def _create_events_for_dates(self, lib, version, dates):
        for date in dates:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="test_id",
                timestamp=date,
                properties={
                    "$lib": lib,
                    "$lib_version": version,
                },
            )

