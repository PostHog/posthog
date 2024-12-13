import uuid

from rest_framework import status

from posthog.models.event.util import create_event
from posthog.models.utils import uuid7
from posthog.test.base import APIBaseTest


class TestSessionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        s1 = str(uuid7())

        create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            properties={"$session_id": s1, "utm_source": "google"},
            event_uuid=(uuid.uuid4()),
        )
        create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            properties={"$session_id": s1, "utm_source": "youtube"},
            event_uuid=(uuid.uuid4()),
        )

    def test_expected_session_properties(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_properties = {entry["name"] for entry in response.json()["results"]}
        expected_properties = {
            "$autocapture_count",
            "$channel_type",
            "$end_timestamp",
            "$entry_current_url",
            "$entry_pathname",
            "$end_current_url",
            "$end_pathname",
            "$entry_gad_source",
            "$entry_gclid",
            "$entry_referring_domain",
            "$entry_utm_campaign",
            "$entry_utm_content",
            "$entry_utm_medium",
            "$entry_utm_source",
            "$entry_utm_term",
            "$pageview_count",
            "$screen_count",
            "$session_duration",
            "$start_timestamp",
            "$is_bounce",
            "$last_external_click_url",
            "$vitals_lcp",
        }
        assert actual_properties == expected_properties

    def test_search_session_properties(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/property_definitions/?search=utm")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_properties = {entry["name"] for entry in response.json()["results"]}
        expected_properties = {
            "$entry_utm_campaign",
            "$entry_utm_content",
            "$entry_utm_medium",
            "$entry_utm_source",
            "$entry_utm_term",
        }
        assert actual_properties == expected_properties

    def test_empty_search_session_properties(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/property_definitions/?search=doesnotexist")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert len(response.json()["results"]) == 0

    def test_list_channel_type_values(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$channel_type")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()}
        expected_values = {
            "Affiliate",
            "Audio",
            "Cross Network",
            "Direct",
            "Email",
            "Organic Search",
            "Organic Shopping",
            "Organic Social",
            "Organic Video",
            "Unknown",
            "Paid Unknown",
            "Paid Search",
            "Paid Shopping",
            "Paid Social",
            "Paid Video",
            "Push",
            "Referral",
            "SMS",
        }
        assert actual_values == expected_values

    def test_search_channel_type_values(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$channel_type&value=paid")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()}
        expected_values = {
            "Paid Unknown",
            "Paid Search",
            "Paid Shopping",
            "Paid Social",
            "Paid Video",
        }
        assert actual_values == expected_values

    def test_list_session_property_values(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()}
        expected_values = {
            "google",
            "youtube",
        }
        assert actual_values == expected_values

    def test_search_session_property_values(self):
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source&value=tub")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()}
        expected_values = {
            "youtube",
        }
        assert actual_values == expected_values

    def test_search_session_property_no_matching_values(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source&value=doesnotexist"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert len(response.json()) == 0

    def test_search_missing_session_property_values(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source&value=doesnotexist"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert len(response.json()) == 0
