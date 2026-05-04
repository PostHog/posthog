import uuid

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.event.util import create_event
from posthog.models.raw_sessions.sessions_v3 import SESSION_V3_LOWER_TIER_AD_IDS
from posthog.models.utils import uuid7

V2_EXPECTED_PROPERTIES = {
    "$autocapture_count",
    "$channel_type",
    "$end_current_url",
    "$end_hostname",
    "$end_pathname",
    "$end_timestamp",
    "$entry__kx",
    "$entry_current_url",
    "$entry_dclid",
    "$entry_fbclid",
    "$entry_gad_source",
    "$entry_gbraid",
    "$entry_gclid",
    "$entry_gclsrc",
    "$entry_hostname",
    "$entry_igshid",
    "$entry_irclid",
    "$entry_li_fat_id",
    "$entry_mc_cid",
    "$entry_msclkid",
    "$entry_pathname",
    "$entry_referring_domain",
    "$entry_ttclid",
    "$entry_twclid",
    "$entry_utm_campaign",
    "$entry_utm_content",
    "$entry_utm_medium",
    "$entry_utm_source",
    "$entry_utm_term",
    "$entry_wbraid",
    "$is_bounce",
    "$last_external_click_url",
    "$pageview_count",
    "$screen_count",
    "$session_duration",
    "$start_timestamp",
    "$vitals_lcp",
}

V3_EXPECTED_PROPERTIES = {
    "$autocapture_count",
    "$channel_type",
    "$emails",
    "$end_current_url",
    "$end_hostname",
    "$end_pathname",
    "$end_timestamp",
    "$entry_current_url",
    "$entry_fbclid",
    "$entry_gad_source",
    "$entry_gclid",
    "$entry_has_fbclid",
    "$entry_has_gclid",
    "$entry_hostname",
    "$entry_pathname",
    "$entry_referring_domain",
    "$entry_utm_campaign",
    "$entry_utm_content",
    "$entry_utm_medium",
    "$entry_utm_source",
    "$entry_utm_term",
    "$has_replay_events",
    "$hosts",
    "$is_bounce",
    "$last_external_click_url",
    "$pageview_count",
    "$screen_count",
    "$session_duration",
    "$start_timestamp",
}

for ad_id in SESSION_V3_LOWER_TIER_AD_IDS:
    V3_EXPECTED_PROPERTIES.add(f"$entry_{ad_id}")
    V3_EXPECTED_PROPERTIES.add(f"$entry_has_{ad_id}")


def _set_session_table_version(team, version):
    if version == "v3":
        team.modifiers = {"sessionTableVersion": "v3"}
        team.save()


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

    @parameterized.expand([("v2",), ("v3",)])
    def test_expected_session_properties(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/property_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_properties = {entry["name"] for entry in response.json()["results"]}
        expected = V2_EXPECTED_PROPERTIES if version == "v2" else V3_EXPECTED_PROPERTIES
        assert actual_properties == expected

    @parameterized.expand([("v2",), ("v3",)])
    def test_search_session_properties(self, version):
        _set_session_table_version(self.team, version)
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

    @parameterized.expand([("v2",), ("v3",)])
    def test_list_channel_type_values(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$channel_type")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()["results"]}
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

    @parameterized.expand([("v2",), ("v3",)])
    def test_search_channel_type_values(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$channel_type&value=paid")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()["results"]}
        expected_values = {
            "Paid Unknown",
            "Paid Search",
            "Paid Shopping",
            "Paid Social",
            "Paid Video",
        }
        assert actual_values == expected_values

    @parameterized.expand([("v2",), ("v3",)])
    def test_list_session_property_values(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()["results"]}
        expected_values = {
            "google",
            "youtube",
        }
        assert actual_values == expected_values

    @parameterized.expand([("v2",), ("v3",)])
    def test_search_session_property_values(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source&value=tub")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        actual_values = {entry["name"] for entry in response.json()["results"]}
        expected_values = {
            "youtube",
        }
        assert actual_values == expected_values

    @parameterized.expand([("v2",), ("v3",)])
    def test_search_session_property_no_matching_values(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(
            f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source&value=doesnotexist"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert len(response.json()["results"]) == 0

    @parameterized.expand([("v2",), ("v3",)])
    def test_numerical_session_properties(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/property_definitions/?is_numerical=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        for entry in results:
            self.assertTrue(entry["is_numerical"], f"Expected {entry['name']} to be numerical")
        actual_properties = {entry["name"] for entry in results}
        expected_numerical = {
            "$autocapture_count",
            "$pageview_count",
            "$screen_count",
            "$session_duration",
        }
        if version == "v2":
            expected_numerical.add("$vitals_lcp")
        self.assertEqual(actual_properties, expected_numerical)

    @parameterized.expand([("v2",), ("v3",)])
    def test_non_numerical_session_properties(self, version):
        _set_session_table_version(self.team, version)
        response = self.client.get(f"/api/projects/{self.team.pk}/sessions/property_definitions/?is_numerical=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        for entry in results:
            self.assertFalse(entry["is_numerical"], f"Expected {entry['name']} to not be numerical")
        numerical_properties = {
            "$autocapture_count",
            "$pageview_count",
            "$screen_count",
            "$session_duration",
            "$vitals_lcp",
        }
        actual_properties = {entry["name"] for entry in results}
        self.assertTrue(actual_properties.isdisjoint(numerical_properties))

    def test_search_missing_session_property_values(self):
        response = self.client.get(
            f"/api/projects/{self.team.pk}/sessions/values/?key=$entry_utm_source&value=doesnotexist"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assert len(response.json()["results"]) == 0
