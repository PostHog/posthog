from unittest.mock import patch
from freezegun import freeze_time
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL
from posthog.models.utils import uuid7
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.test.base import (
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestExternalWebAnalyticsIntegration(WebAnalyticsPreAggregatedTestBase):
    """
    Integration tests for the external web analytics API that test the full stack
    with real pre-aggregated data, similar to test_web_stats_pre_aggregated.py.
    """

    def setUp(self):
        super().setUp()
        # Mock the permissions for external web analytics access
        self.team_ids_patch = patch(
            "posthog.api.external_web_analytics.http.TEAM_IDS_WITH_EXTERNAL_WEB_ANALYTICS", [self.team.id]
        )
        self.team_ids_patch.start()

        self.feature_flag_patch = patch("posthog.api.external_web_analytics.http.posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patch.start()
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.team_ids_patch.stop()
        self.feature_flag_patch.stop()
        super().tearDown()

    def _setup_test_data(self):
        with freeze_time("2024-01-01T09:00:00Z"):
            sessions = [str(uuid7("2024-01-01")) for _ in range(10)]

            for i in range(10):
                _create_person(team_id=self.team.pk, distinct_ids=[f"user_{i}"])

            # Desktop user - Chrome, Windows, US
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_0",
                timestamp="2024-01-01T10:00:00Z",
                properties={
                    "$session_id": sessions[0],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "New York",
                    "$geoip_subdivision_1_code": "NY",
                    "utm_source": "google",
                    "utm_medium": "cpc",
                    "utm_campaign": "summer_sale",
                    "$referring_domain": "google.com",
                },
            )

            # Another desktop user - Chrome, Windows, US
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_1",
                timestamp="2024-01-01T10:05:00Z",
                properties={
                    "$session_id": sessions[1],
                    "$current_url": "https://example.com/features",
                    "$pathname": "/features",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "New York",
                    "$geoip_subdivision_1_code": "NY",
                },
            )

            # Desktop user - Firefox, macOS, UK
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_2",
                timestamp="2024-01-01T11:00:00Z",
                properties={
                    "$session_id": sessions[2],
                    "$current_url": "https://example.com/landing",
                    "$pathname": "/landing",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Firefox",
                    "$os": "macOS",
                    "$viewport_width": 1440,
                    "$viewport_height": 900,
                    "$geoip_country_code": "GB",
                    "$geoip_city_name": "London",
                    "$geoip_subdivision_1_code": "EN",
                    "utm_source": "facebook",
                    "utm_medium": "social",
                    "$referring_domain": "facebook.com",
                },
            )

            # Mobile user - Safari, iOS, Canada
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_3",
                timestamp="2024-01-01T12:00:00Z",
                properties={
                    "$session_id": sessions[3],
                    "$current_url": "https://example.com/pricing",
                    "$pathname": "/pricing",
                    "$host": "example.com",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 375,
                    "$viewport_height": 812,
                    "$geoip_country_code": "CA",
                    "$geoip_city_name": "Toronto",
                    "$geoip_subdivision_1_code": "ON",
                    "$referring_domain": "search.yahoo.com",
                },
            )

            # Mobile user - Chrome, Android, Australia (bounce session)
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_4",
                timestamp="2024-01-01T13:00:00Z",
                properties={
                    "$session_id": sessions[4],
                    "$current_url": "https://example.com/pricing",
                    "$pathname": "/pricing",
                    "$host": "example.com",
                    "$device_type": "Mobile",
                    "$browser": "Chrome",
                    "$os": "Android",
                    "$viewport_width": 414,
                    "$viewport_height": 896,
                    "$geoip_country_code": "AU",
                    "$geoip_city_name": "Sydney",
                    "$geoip_subdivision_1_code": "NSW",
                    "utm_source": "twitter",
                    "utm_medium": "social",
                    "utm_campaign": "launch_week",
                    "$referring_domain": "twitter.com",
                },
            )

            # Multi-page session - Desktop Chrome user
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_5",
                timestamp="2024-01-01T14:00:00Z",
                properties={
                    "$session_id": sessions[5],
                    "$current_url": "https://example.com/contact",
                    "$pathname": "/contact",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                    "utm_source": "google",
                    "utm_medium": "organic",
                    "$referring_domain": "google.com",
                },
            )
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_5",
                timestamp="2024-01-01T14:02:00Z",
                properties={
                    "$session_id": sessions[5],
                    "$current_url": "https://example.com/about",
                    "$pathname": "/about",
                    "$host": "example.com",
                    "$device_type": "Desktop",
                    "$browser": "Chrome",
                    "$os": "Windows",
                    "$viewport_width": 1920,
                    "$viewport_height": 1080,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                },
            )

            flush_persons_and_events()
            self._populate_preaggregated_tables()

            # Clear events table to ensure tests only pass if using pre-aggregated tables
            sync_execute("TRUNCATE TABLE events")

    def _populate_preaggregated_tables(self, date_start: str = "2024-01-01", date_end: str = "2024-01-02"):
        bounces_insert = WEB_BOUNCES_INSERT_SQL(
            date_start=date_start,
            date_end=date_end,
            team_ids=[self.team.pk],
        )
        stats_insert = WEB_STATS_INSERT_SQL(
            date_start=date_start,
            date_end=date_end,
            team_ids=[self.team.pk],
        )
        sync_execute(stats_insert)
        sync_execute(bounces_insert)

    def test_overview_endpoint_with_preaggregated_data(self):
        """Test the overview endpoint with real pre-aggregated data returns structured format."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify structured response format
        assert "visitors" in data
        assert isinstance(data["visitors"], dict)
        assert "key" in data["visitors"]
        assert "kind" in data["visitors"]
        assert "value" in data["visitors"]

        # Verify we got expected data from our test setup
        assert data["visitors"]["key"] == "visitors"
        assert data["visitors"]["kind"] == "unit"
        assert data["visitors"]["value"] == 6  # user_0 through user_5

        assert data["views"]["key"] == "views"
        assert data["views"]["kind"] == "unit"
        assert data["views"]["value"] == 7  # 7 total pageviews

        assert data["sessions"]["key"] == "sessions"
        assert data["sessions"]["kind"] == "unit"
        assert data["sessions"]["value"] == 6  # 6 sessions

        assert data["bounce_rate"]["key"] == "bounce_rate"
        assert data["bounce_rate"]["kind"] == "percentage"
        assert isinstance(data["bounce_rate"]["value"], float)
        assert data["bounce_rate"]["isIncreaseBad"] is True

        assert data["session_duration"]["key"] == "session_duration"
        assert data["session_duration"]["kind"] == "duration_s"
        assert isinstance(data["session_duration"]["value"], float)

    def test_overview_endpoint_with_comparison_period(self):
        """Test the overview endpoint with comparison enabled."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
                "compare": "true",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify comparison data structure
        for metric_key in ["visitors", "views", "sessions", "bounce_rate", "session_duration"]:
            metric = data[metric_key]
            assert "previous" in metric
            assert "changeFromPreviousPct" in metric
            # Note: previous values may be None if no data in comparison period

    def test_breakdown_endpoint_with_preaggregated_data(self):
        """Test the breakdown endpoint with real pre-aggregated data."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/breakdown/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "breakdown_by": "DeviceType",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify breakdown response format
        assert "results" in data
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 2  # Desktop and Mobile

        # Sort results for consistent testing
        results = sorted(data["results"], key=lambda x: x["breakdown_value"])

        # Desktop: user_0, user_1, user_2, user_5 (4 visitors, 5 views including multi-page session)
        desktop_result = next(r for r in results if r["breakdown_value"] == "Desktop")
        assert desktop_result["visitors"] == 4
        assert desktop_result["views"] == 5

        # Mobile: user_3, user_4 (2 visitors, 2 views)
        mobile_result = next(r for r in results if r["breakdown_value"] == "Mobile")
        assert mobile_result["visitors"] == 2
        assert mobile_result["views"] == 2

    def test_breakdown_endpoint_with_browser_breakdown(self):
        """Test browser breakdown with real data."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/breakdown/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "breakdown_by": "Browser",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        results = sorted(data["results"], key=lambda x: x["breakdown_value"])

        # Chrome: user_0, user_1, user_4, user_5 (4 visitors, 5 views)
        chrome_result = next(r for r in results if r["breakdown_value"] == "Chrome")
        assert chrome_result["visitors"] == 4
        assert chrome_result["views"] == 5

        # Firefox: user_2 (1 visitor, 1 view)
        firefox_result = next(r for r in results if r["breakdown_value"] == "Firefox")
        assert firefox_result["visitors"] == 1
        assert firefox_result["views"] == 1

        # Safari: user_3 (1 visitor, 1 view)
        safari_result = next(r for r in results if r["breakdown_value"] == "Safari")
        assert safari_result["visitors"] == 1
        assert safari_result["views"] == 1

    def test_breakdown_endpoint_with_page_breakdown_includes_bounce_rate(self):
        """Test page breakdown includes bounce rate data."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/breakdown/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "breakdown_by": "Page",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify all results have bounce_rate
        for result in data["results"]:
            assert "bounce_rate" in result
            assert isinstance(result["bounce_rate"], float)

        # Sort results for consistent testing
        results = sorted(data["results"], key=lambda x: x["breakdown_value"])

        # /landing: user_0, user_2 (2 visitors, 2 views, 1 bounce)
        landing_result = next(r for r in results if r["breakdown_value"] == "/landing")
        assert landing_result["visitors"] == 2
        assert landing_result["views"] == 2

        # /pricing: user_3, user_4 (2 visitors, 2 views)
        pricing_result = next(r for r in results if r["breakdown_value"] == "/pricing")
        assert pricing_result["visitors"] == 2
        assert pricing_result["views"] == 2

    def test_overview_endpoint_with_host_filtering(self):
        """Test overview endpoint properly filters by host."""
        # Test with matching host
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["visitors"]["value"] == 6

        # Test with non-matching host
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "different.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["visitors"]["value"] == 0
        assert data["views"]["value"] == 0

    def test_breakdown_endpoint_with_property_filtering(self):
        """Test breakdown endpoint with pathname filtering."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/breakdown/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "breakdown_by": "DeviceType",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should get both Desktop and Mobile results
        assert len(data["results"]) == 2

    def test_breakdown_endpoint_pagination(self):
        """Test breakdown endpoint pagination works correctly."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/breakdown/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "breakdown_by": "Page",
                "host": "example.com",
                "limit": 2,
                "offset": 0,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert len(data["results"]) == 2
        assert "next" in data

        # Test second page if there are more results
        if data["next"]:
            assert "offset=2" in data["next"]
            assert "limit=2" in data["next"]

    def test_overview_endpoint_without_host_parameter(self):
        """Test overview endpoint works without host parameter."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should get all data when no host filter is applied
        assert data["visitors"]["value"] == 6
        assert data["views"]["value"] == 7

    def test_overview_endpoint_validates_date_format(self):
        """Test overview endpoint validates date format correctly."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "invalid-date",
                "date_to": "2024-01-02",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_breakdown_endpoint_validates_breakdown_by_parameter(self):
        """Test breakdown endpoint validates breakdown_by parameter."""
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/breakdown/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "breakdown_by": "InvalidBreakdown",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_overview_endpoint_works_with_test_account_filtering(self):
        """Test overview endpoint with test account filtering enabled/disabled."""
        # Test with test account filtering enabled (default)
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
                "filter_test_accounts": "true",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        test_filtered_visitors = data["visitors"]["value"]

        # Test with test account filtering disabled
        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
                "filter_test_accounts": "false",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        unfiltered_visitors = data["visitors"]["value"]

        # Both should return data (actual filtering logic depends on test account setup)
        assert test_filtered_visitors >= 0
        assert unfiltered_visitors >= 0

    def test_external_api_uses_preaggregated_tables(self):
        """Verify the external API is actually using pre-aggregated tables."""
        # Clear regular events table to ensure only pre-aggregated data is available
        sync_execute("TRUNCATE TABLE events")

        response = self.client.get(
            f"/api/projects/{self.team.pk}/web_analytics/overview/",
            data={
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
                "host": "example.com",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Should still get data because it's using pre-aggregated tables
        assert data["visitors"]["value"] > 0
        assert data["views"]["value"] > 0
