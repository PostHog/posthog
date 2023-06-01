import base64
import json
from unittest.mock import patch
import time


from django.core.cache import cache
from django.db import connection
from django.test.client import Client
from rest_framework import status

from posthog.api.test.test_feature_flag import QueryTimeoutWrapper
from posthog.models import FeatureFlag, GroupTypeMapping, Person, PersonalAPIKey, Plugin, PluginConfig, PluginSourceFile
from posthog.models.cohort.cohort import Cohort
from posthog.models.personal_api_key import hash_key_value
from posthog.models.plugin import sync_team_inject_web_apps
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import BaseTest, QueryMatchingTest, snapshot_postgres_queries, snapshot_postgres_queries_context
from posthog.utils import is_postgres_connected_cached_check


@patch("posthog.models.feature_flag.flag_matching.is_postgres_connected_cached_check", return_value=True)
class TestDecide(BaseTest, QueryMatchingTest):
    """
    Tests the `/decide` endpoint.
    We use Django's base test class instead of DRF's because we need granular control over the Content-Type sent over.
    """

    def setUp(self, *args):
        cache.clear()

        super().setUp()
        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(
        self,
        data=None,
        origin="http://127.0.0.1:8000",
        api_version=1,
        distinct_id="example_id",
        groups={},
        geoip_disable=False,
        ip="127.0.0.1",
    ):
        return self.client.post(
            f"/decide/?v={api_version}",
            {
                "data": self._dict_to_b64(
                    data
                    or {
                        "token": self.team.api_token,
                        "distinct_id": distinct_id,
                        "groups": groups,
                        "geoip_disable": geoip_disable,
                    },
                )
            },
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    def _update_team(self, data):
        # use a non-csrf client to make requests
        client = Client()
        client.force_login(self.user)

        response = client.patch("/api/projects/@current/", data, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        client.logout()

    def test_defaults_to_v2_if_conflicting_parameters(self, *args):
        """
        regression test for https://sentry.io/organizations/posthog2/issues/2738865125/?project=1899813
        posthog-js version 1.19.0 (but not versions before or after)
        mistakenly sent two `v` parameters to the decide endpoint
        one was correct "2"
        the other incorrect "1.19.0"

        as a result, if there is a value error reading the `v` param, decide now defaults to 2
        """

        response = self.client.post(
            f"/decide/?v=2&v=1.19.0",
            {"data": self._dict_to_b64({"token": self.team.api_token, "distinct_id": "example_id", "groups": {}})},
            HTTP_ORIGIN="http://127.0.0.1:8000",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_on_evil_site(self, *args):
        user = self.organization.members.first()
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        response = self.client.get("/decide/", HTTP_ORIGIN="https://evilsite.com").json()
        self.assertEqual(response["isAuthenticated"], False)
        self.assertIsNone(response["toolbarParams"].get("toolbarVersion", None))

    def test_user_session_recording_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self._update_team({"session_recording_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": False},
        )
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])

    def test_user_session_recording_version(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        # don't access models directly as that doesn't update the cache.
        self._update_team({"session_recording_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": False},
        )

        self._update_team({"session_recording_version": "v2"})

        response = self._post_decide().json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v2", "consoleLogRecordingEnabled": False},
        )

    def test_user_console_log_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self._update_team({"session_recording_opt_in": True, "capture_console_log_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": True},
        )

    def test_user_performance_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["capturePerformance"], False)

        self._update_team({"capture_performance_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(response["capturePerformance"], True)

    def test_user_session_recording_opt_in_wildcard_domain(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self._update_team({"session_recording_opt_in": True, "recording_domains": ["https://*.example.com"]})

        response = self._post_decide(origin="https://random.example.com").json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": False},
        )
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])

        # Make sure the domain matches exactly
        response = self._post_decide(origin="https://random.example.com.evilsite.com").json()
        self.assertEqual(response["sessionRecording"], False)

    def test_user_session_recording_evil_site(self, *args):

        self._update_team({"session_recording_opt_in": True, "recording_domains": ["https://example.com"]})

        response = self._post_decide(origin="evil.site.com").json()
        self.assertEqual(response["sessionRecording"], False)

        response = self._post_decide(origin="https://example.com").json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": False},
        )

    def test_user_autocapture_opt_out(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["autocapture_opt_out"], False)

        self._update_team({"autocapture_opt_out": True})

        response = self._post_decide().json()
        self.assertEqual(response["autocapture_opt_out"], True)

    def test_user_session_recording_allowed_when_no_permitted_domains_are_set(self, *args):

        self._update_team({"session_recording_opt_in": True, "recording_domains": []})

        response = self._post_decide(origin="any.site.com").json()
        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": False},
        )

    @snapshot_postgres_queries
    def test_web_app_queries(self, *args):
        with self.assertNumQueries(2):
            response = self._post_decide()
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        PluginConfig.objects.create(
            plugin=plugin, enabled=True, order=1, team=self.team, config={}, web_token="tokentoken"
        )
        sync_team_inject_web_apps(self.team)

        # caching flag definitions in the above mean fewer queries
        # 3 of these queries are just for setting transaction scope
        with self.assertNumQueries(4):
            response = self._post_decide()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            injected = response.json()["siteApps"]
            self.assertEqual(len(injected), 1)

    def test_site_app_injection(self, *args):
        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        plugin_config = PluginConfig.objects.create(
            plugin=plugin, enabled=True, order=1, team=self.team, config={}, web_token="tokentoken"
        )
        self.team.refresh_from_db()
        self.assertTrue(self.team.inject_web_apps)
        with self.assertNumQueries(5):
            response = self._post_decide()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            injected = response.json()["siteApps"]
            self.assertEqual(len(injected), 1)
            self.assertTrue(injected[0]["url"].startswith(f"/site_app/{plugin_config.id}/{plugin_config.web_token}/"))

    def test_feature_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone

        # Test number of queries with multiple property filter feature flags
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=50,
            name="Filter by property",
            key="filer-by-property",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]}]},
            name="Filter by property 2",
            key="filer-by-property-2",
            created_by=self.user,
        )

        with self.assertNumQueries(4):
            response = self._post_decide()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("default-flag", response.json()["featureFlags"])
        self.assertIn("beta-feature", response.json()["featureFlags"])
        self.assertIn("filer-by-property-2", response.json()["featureFlags"])

        # caching flag definitions in the above query mean fewer queries
        with self.assertNumQueries(4):
            response = self._post_decide({"token": self.team.api_token, "distinct_id": "another_id"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["featureFlags"], ["default-flag"])

    def test_feature_flags_v3_json(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "payloads": {"true": {"color": "blue"}},
            },
            name="Filter by property",
            key="filter-by-property",
            created_by=self.user,
        )

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual({"color": "blue"}, response.json()["featureFlagPayloads"]["filter-by-property"])

    def test_feature_flags_v3_json_multivariate(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
                "payloads": {"first-variant": {"color": "blue"}},
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(0):
            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("beta-feature", response.json()["featureFlags"])
            self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])
            self.assertEqual({"color": "blue"}, response.json()["featureFlagPayloads"]["multivariate-flag"])

    def test_feature_flags_v2(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=1)  # v1 functionality should not break
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("beta-feature", response.json()["featureFlags"])
            self.assertIn("default-flag", response.json()["featureFlags"])

        # caching flag definitions in the above query mean fewer queries
        with self.assertNumQueries(0):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=2, distinct_id="other_id")
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "third-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, different variant assigned

    def test_feature_flags_v2_with_property_overrides(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$geoip_country_name": "India"})
        Person.objects.create(team=self.team, distinct_ids=["other_id"], properties={})

        australia_ip = "13.106.122.3"

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "$geoip_country_name", "value": "Australia", "type": "person"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "$geoip_country_name", "value": "India", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=2, ip=australia_ip)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])

        # caching flag definitions in the above mean fewer queries
        with self.assertNumQueries(0):
            response = self._post_decide(api_version=2, distinct_id="other_id", ip=australia_ip)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])

    def test_feature_flags_v2_with_geoip_error(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$geoip_country_name": "India"})
        Person.objects.create(team=self.team, distinct_ids=["other_id"], properties={})

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "$geoip_country_name", "value": "Australia", "type": "person"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "$geoip_country_name", "value": "India", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(4):
            # One to compute properties for all flags
            response = self._post_decide(api_version=2, distinct_id="example_id")
            self.assertTrue("beta-feature" not in response.json()["featureFlags"])
            self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="other_id")
            self.assertTrue("beta-feature" not in response.json()["featureFlags"])
            self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])

    def test_feature_flags_v2_consistent_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"}
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(5):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # new person, merged from old distinct ID
        # person.delete()
        # person2 = Person.objects.create(team=self.team, distinct_ids=["example_id", "other_id"], properties={"email": "tim@posthog.com"})
        person.add_distinct_id("other_id")

        with self.assertNumQueries(9):
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": "other_id", "$anon_distinct_id": "example_id"},
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, overridden by distinct_id, same variant assigned

    def test_feature_flags_v3_consistent_flags_with_numeric_distinct_ids(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=[1], properties={"email": "tim@posthog.com"})
        Person.objects.create(team=self.team, distinct_ids=[12345, "xyz"], properties={"email": "tim@posthog.com"})
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(5):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])

        with self.assertNumQueries(9):
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": 12345, "$anon_distinct_id": "example_id"},
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])

        with self.assertNumQueries(9):
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": "xyz", "$anon_distinct_id": 12345},
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])

        with self.assertNumQueries(9):
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": 5, "$anon_distinct_id": 12345},
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])

    def test_feature_flags_v2_consistent_flags_with_ingestion_delays(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        # We're simulating ingestion delays, so this person below we expect to be created isn't created yet
        # person = Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # identify event is sent, but again, ingestion delays, so no entry in personDistinctID table
        # person.add_distinct_id("other_id")
        # in which case, we're pretty much trashed
        with self.assertNumQueries(8):
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": "other_id", "$anon_distinct_id": "example_id"},
            )
            # self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "third-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, should've been overridden by distinct_id, but ingestion delays mean different variant assigned

    def test_feature_flags_v2_consistent_flags_with_merged_persons(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"}
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(5):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # new person, created separately before "example_id" came into the picture.
        # on identify, this will trigger a merge with person.id being deleted, and
        # `example_id` becoming a part of person2.
        person2 = Person.objects.create(
            team=self.team, distinct_ids=["other_id"], properties={"email": "tim@posthog.com"}
        )

        # caching flag definitions in the above mean fewer queries
        with self.assertNumQueries(9):
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": "other_id", "$anon_distinct_id": "example_id"},
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, overridden by distinct_id, same variant assigned

        # now let's say a merge happens with a call like: identify(distinct_id='example_id', anon_distinct_id='other_id')
        # that is, person2 is going to get merged into person. (Could've been vice versa, but the following code assumes this, it's symmetric.)
        new_person_id = person.id
        old_person_id = person2.id
        # this happens in the plugin server
        # https://github.com/PostHog/posthog/blob/master/plugin-server/src/worker/ingestion/person-state.ts#L696 (addFeatureFlagHashKeysForMergedPerson)
        # at which point we run the query
        query = f"""
            WITH deletions AS (
                    DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id = {old_person_id}
                    RETURNING team_id, person_id, feature_flag_key, hash_key
                )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, {new_person_id}, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING
        """
        with connection.cursor() as cursor:
            cursor.execute(query)

        person2.delete()
        person.add_distinct_id("other_id")

        # caching flag definitions in the above mean fewer queries
        with self.assertNumQueries(5):
            response = self._post_decide(api_version=2, data={"token": self.team.api_token, "distinct_id": "other_id"})
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, overridden by distinct_id, same variant assigned

    def test_feature_flags_v2_consistent_flags_with_delayed_new_identified_person(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"}
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(5):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # new person with "other_id" is yet to be created

        # caching flag definitions in the above mean fewer queries
        with self.assertNumQueries(9):
            # one extra query to find person_id for $anon_distinct_id
            response = self._post_decide(
                api_version=2,
                data={"token": self.team.api_token, "distinct_id": "other_id", "$anon_distinct_id": "example_id"},
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, overridden by distinct_id, same variant assigned

        # calling a simple decide call, while 'other_id' is still missing a person creation.
        # In this case, we are over our grace period for ingestion, and there's
        # no quick decent way to find how 'other_id' is to be treated.
        # So, things appear like a completely new person with distinct-id = other_id.
        # And this person can't have any hash key overrides (since the person doesn't yet exist)
        # So one fewer query to not get overrides.
        with self.assertNumQueries(4):
            # caching flag definitions in the above mean fewer queries

            response = self._post_decide(api_version=2, data={"token": self.team.api_token, "distinct_id": "other_id"})
            # self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual("third-variant", response.json()["featureFlags"]["multivariate-flag"])  # variant changed

        person.add_distinct_id("other_id")
        # Finally, 'other_id' is merged. The result goes back to its overridden values

        # caching flag definitions in the above mean fewer queries
        with self.assertNumQueries(5):
            response = self._post_decide(api_version=2, data={"token": self.team.api_token, "distinct_id": "other_id"})
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, overridden by distinct_id, same variant assigned

    def test_feature_flags_v2_complex(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com", "realm": "cloud"}
        )
        Person.objects.create(
            team=self.team, distinct_ids=["hosted_id"], properties={"email": "sam@posthog.com", "realm": "hosted"}
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {"properties": [{"key": "realm", "type": "person", "value": "cloud"}], "rollout_percentage": 80}
                ],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 25},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        {"key": "fourth-variant", "name": "Fourth Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with top-level property filtering and percentage rollout.",
            key="multivariate-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="hosted_id")
            self.assertIsNone(
                (response.json()["featureFlags"]).get("multivariate-flag", None)
            )  # User is does not have realm == "cloud". Value is None.
            self.assertTrue(
                (response.json()["featureFlags"]).get("default-flag")
            )  # User still receives the default flag

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="example_id")
            self.assertIsNotNone(
                response.json()["featureFlags"]["multivariate-flag"]
            )  # User has an 80% chance of being assigned any non-empty value.
            self.assertEqual(
                "second-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # If the user falls in the rollout group, they have a 25% chance of being assigned any particular variant.
            # Their overall probability is therefore 80% * 25% = 20%.
            # To give another example, if n = 100 Cloud users and rollout_percentage = 80:
            # None:           20 (100 * (100% - 80%))
            # first-variant:  20 (100 * 80% * 25% = 20 users)
            # second-variant: 20 (100 * 80% * 25% = 20 users)
            # third-variant:  20 (100 * 80% * 25% = 20 users)
            # fourth-variant: 20 (100 * 80% * 25% = 20 users)

    def test_feature_flags_v3(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {"groups": [{"rollout_percentage": 50}]},
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "multivariate-flag",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # At this stage, our cache should have all 3 flags

        # also adding team to cache
        self._post_decide(api_version=3)
        client.logout()

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=3)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=3, distinct_id="other_id")
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "third-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, different variant assigned
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_database_errors(self, mock_counter, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [{"key": "email", "value": "tim", "type": "person", "operator": "icontains"}],
                            "rollout_percentage": 50,
                        }
                    ]
                },
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "multivariate-flag",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                            {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                            {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                        ]
                    },
                },
            },
            format="json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # At this stage, our cache should have all 3 flags

        # also adding team to cache
        self._post_decide(api_version=3)

        client.logout()

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=3)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        # now database is down
        with connection.execute_wrapper(QueryTimeoutWrapper()):
            response = self._post_decide(api_version=3, distinct_id="example_id")
            self.assertTrue("beta-feature" not in response.json()["featureFlags"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])
            self.assertTrue(response.json()["errorsWhileComputingFlags"])

            mock_counter.labels.assert_called_once_with(reason="timeout")

    def test_feature_flags_v3_with_database_errors_and_no_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        # adding team to cache
        self._post_decide(api_version=3)

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.json()["featureFlags"], {})
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        # now database is down
        with connection.execute_wrapper(QueryTimeoutWrapper()):
            response = self._post_decide(api_version=3, distinct_id="example_id")
            self.assertEqual(response.json()["featureFlags"], {})
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v3_with_database_errors_and_geoip_properties(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        australia_ip = "13.106.122.3"

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={})

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "$geoip_country_name",
                                    "value": "Australia",
                                    "type": "person",
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # At this stage, our cache should have both flags

        # also adding team to cache
        self._post_decide(api_version=3)

        client.logout()

        with self.assertNumQueries(0):
            response = self._post_decide(api_version=3, ip=australia_ip)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        # now database is down
        with connection.execute_wrapper(QueryTimeoutWrapper()):
            response = self._post_decide(api_version=3, distinct_id="example_id", ip=australia_ip)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v3_consistent_flags_with_database_errors(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"}
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 50},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 25},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 25},
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        # make sure caches are populated
        response = self._post_decide(api_version=3)

        with self.assertNumQueries(5):
            # effectively 3 queries, wrapped around by an atomic transaction
            # E   1. SAVEPOINT "s4379526528_x103"
            # E   2. SET LOCAL statement_timeout = 1000
            # E   3. SELECT "posthog_persondistinctid"."person_id", "posthog_persondistinctid"."distinct_id" FROM "posthog_persondistinctid"
            #           WHERE ("posthog_persondistinctid"."distinct_id" IN ('example_id') AND "posthog_persondistinctid"."team_id" = 1)
            # E   4. SELECT "posthog_featureflaghashkeyoverride"."feature_flag_key", "posthog_featureflaghashkeyoverride"."hash_key", "posthog_featureflaghashkeyoverride"."person_id" FROM "posthog_featureflaghashkeyoverride"
            #            WHERE ("posthog_featureflaghashkeyoverride"."person_id" IN (7) AND "posthog_featureflaghashkeyoverride"."team_id" = 1)
            # E   5. RELEASE SAVEPOINT "s4379526528_x103"
            response = self._post_decide(api_version=3)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # new person, merged from old distinct ID
        person.add_distinct_id("other_id")

        # now database is down
        with connection.execute_wrapper(QueryTimeoutWrapper()):
            response = self._post_decide(
                api_version=3,
                data={"token": self.team.api_token, "distinct_id": "other_id", "$anon_distinct_id": "example_id"},
            )
            self.assertTrue("beta-feature" not in response.json()["featureFlags"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertTrue(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v2_with_groups(self, *args):
        # More in-depth tests in posthog/api/test/test_feature_flag.py

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        Person.objects.create(
            team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com", "realm": "cloud"}
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"aggregation_group_type_index": 0, "groups": [{"rollout_percentage": 100}]},
            name="This is a group-based flag",
            key="groups-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="example_id")
            self.assertEqual(response.json()["featureFlags"], {})

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="example_id", groups={"organization": "foo"})
            self.assertEqual(response.json()["featureFlags"], {"groups-flag": True})

    def test_feature_flags_with_personal_api_key(self, *args):
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(key_value))
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Test", key="test", created_by=self.user
        )
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Disabled", key="disabled", created_by=self.user, active=False
        )  # disabled flag
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="default-flag",
            created_by=self.user,
        )  # enabled for everyone
        response = self._post_decide(
            {"distinct_id": "example_id", "api_key": key_value, "project_id": self.team.id}
        ).json()
        self.assertEqual(response["featureFlags"], ["test", "default-flag"])

    @snapshot_postgres_queries
    def test_flag_with_regular_cohorts(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(team=self.team, distinct_ids=["example_id_1"], properties={"$some_prop_1": "something_1"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop_1", "value": "something_1", "type": "person"}]}],
            name="cohort1",
        )
        # no calculation for cohort

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        with self.assertNumQueries(5):
            response = self._post_decide(api_version=3, distinct_id="example_id_1")
            self.assertEqual(response.json()["featureFlags"], {"cohort-flag": True})
            self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

        with self.assertNumQueries(5):
            # get cohort, get person filter
            response = self._post_decide(api_version=3, distinct_id="another_id")
            self.assertEqual(response.json()["featureFlags"], {"cohort-flag": False})
            self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

    @snapshot_postgres_queries
    def test_flag_with_behavioural_cohorts(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(team=self.team, distinct_ids=["example_id_1"], properties={"$some_prop_1": "something_1"})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {"event_id": "$pageview", "days": 7},
                {"properties": [{"key": "$some_prop_1", "value": "something_1", "type": "person"}]},
            ],
            name="cohort1",
        )
        # no calculation for cohort

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        with self.assertNumQueries(5):
            response = self._post_decide(api_version=3, distinct_id="example_id_1")
            self.assertEqual(response.json()["featureFlags"], {})
            self.assertEqual(response.json()["errorsWhileComputingFlags"], True)

        with self.assertNumQueries(5):
            response = self._post_decide(api_version=3, distinct_id="another_id")
            self.assertEqual(response.json()["featureFlags"], {})
            self.assertEqual(response.json()["errorsWhileComputingFlags"], True)

    def test_personal_api_key_without_project_id(self, *args):
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(key_value))
        Person.objects.create(team=self.team, distinct_ids=["example_id"])

        response = self._post_decide({"distinct_id": "example_id", "api_key": key_value})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            {
                "type": "authentication_error",
                "code": "invalid_api_key",
                "detail": "Project API key invalid. You can find your project API key in PostHog project settings.",
                "attr": None,
            },
        )

    def test_missing_token(self, *args):
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Test", key="test", created_by=self.user
        )
        response = self._post_decide({"distinct_id": "example_id", "api_key": None, "project_id": self.team.id})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_payload_on_decide_endpoint(self, *args):

        invalid_payloads = [base64.b64encode(b"1-1").decode("utf-8"), "1==1", "{distinct_id-1}"]

        for payload in invalid_payloads:
            response = self.client.post("/decide/", {"data": payload}, HTTP_ORIGIN="http://127.0.0.1:8000")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            response_data = response.json()
            detail = response_data.pop("detail")
            self.assertEqual(response.json(), {"type": "validation_error", "code": "malformed_data", "attr": None})
            self.assertIn("Malformed request data:", detail)

    def test_invalid_gzip_payload_on_decide_endpoint(self, *args):

        response = self.client.post(
            "/decide/?compression=gzip",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03",
            HTTP_ORIGIN="http://127.0.0.1:8000",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        detail = response_data.pop("detail")
        self.assertEqual(response.json(), {"type": "validation_error", "code": "malformed_data", "attr": None})
        self.assertIn("Malformed request data:", detail)

    def test_geoip_disable(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"$geoip_country_name": "India"})

        australia_ip = "13.106.122.3"

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Beta feature 1",
            key="australia-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "$geoip_country_name", "value": "Australia", "type": "person"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Beta feature 2",
            key="india-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "$geoip_country_name", "value": "India", "type": "person"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        with self.assertNumQueries(4):
            geoip_not_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable=False)
            geoip_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable=True)

            # person has geoip_country_name set to India, but australia-feature is true, because geoip resolution of current IP is enabled
            self.assertEqual(
                geoip_not_disabled_res.json()["featureFlags"], {"australia-feature": True, "india-feature": False}
            )
            # person has geoip_country_name set to India, and australia-feature is false, because geoip resolution of current IP is disabled
            self.assertEqual(
                geoip_disabled_res.json()["featureFlags"], {"australia-feature": False, "india-feature": True}
            )

        # test for falsy/truthy values
        geoip_not_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable="0")
        geoip_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable="yes")

        # person has geoip_country_name set to India, but australia-feature is true, because geoip resolution of current IP is enabled
        self.assertEqual(
            geoip_not_disabled_res.json()["featureFlags"], {"australia-feature": True, "india-feature": False}
        )
        # person has geoip_country_name set to India, and australia-feature is false, because geoip resolution of current IP is disabled
        self.assertEqual(geoip_disabled_res.json()["featureFlags"], {"australia-feature": False, "india-feature": True})

    @snapshot_postgres_queries
    def test_decide_doesnt_error_out_when_database_is_down(self, *args):
        ALL_TEAM_PARAMS_FOR_DECIDE = {
            "session_recording_opt_in": True,
            "capture_console_log_opt_in": True,
            "inject_web_apps": True,
            "recording_domains": ["https://*.example.com"],
            "capture_performance_opt_in": True,
        }
        self._update_team(ALL_TEAM_PARAMS_FOR_DECIDE)

        response = self._post_decide(api_version=2, origin="https://random.example.com").json()

        self.assertEqual(
            response["sessionRecording"],
            {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": True},
        )
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])
        self.assertEqual(response["siteApps"], [])
        self.assertEqual(response["capturePerformance"], True)
        self.assertEqual(response["featureFlags"], {})

        # now database is down
        with connection.execute_wrapper(QueryTimeoutWrapper()):
            response = self._post_decide(api_version=2, origin="https://random.example.com").json()

            self.assertEqual(
                response["sessionRecording"],
                {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": True},
            )
            self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])
            self.assertEqual(response["siteApps"], [])
            self.assertEqual(response["capturePerformance"], True)
            self.assertEqual(response["featureFlags"], {})

    def test_decide_with_json_and_numeric_distinct_ids(self, *args):
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=[
                "a",
                "{'id': 33040, 'shopify_domain': 'xxx.myshopify.com', 'shopify_token': 'shpat_xxxx', 'created_at': '2023-04-17T08:55:34.624Z', 'updated_at': '2023-04-21T08:43:34.479'}",
                "{'x': 'y'}",
                '{"x": "z"}',
            ],
            properties={"email": "tim@posthog.com", "realm": "cloud"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
            name="This is a group-based flag",
            key="random-flag",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=100,
            name="Filter by property",
            key="filer-by-property",
            created_by=self.user,
        )

        self._post_decide(api_version=2, distinct_id="a")

        # caching flag definitions mean fewer queries
        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id=12345)
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True})

        with self.assertNumQueries(4):
            response = self._post_decide(
                api_version=2,
                distinct_id={
                    "id": 33040,
                    "shopify_domain": "xxx.myshopify.com",
                    "shopify_token": "shpat_xxxx",
                    "created_at": "2023-04-17T08:55:34.624Z",
                    "updated_at": "2023-04-21T08:43:34.479",
                },
            )
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True, "filer-by-property": True})

        with self.assertNumQueries(4):
            response = self._post_decide(
                api_version=2,
                distinct_id="{'id': 33040, 'shopify_domain': 'xxx.myshopify.com', 'shopify_token': 'shpat_xxxx', 'created_at': '2023-04-17T08:55:34.624Z', 'updated_at': '2023-04-21T08:43:34.479'",
            )
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True})

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id={"x": "y"})
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True, "filer-by-property": True})

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id={"x": "z"})
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True})
            # need to pass in exact string to get the property flag

    def test_rate_limits(self, *args):
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="y", DECIDE_BUCKET_REPLENISH_RATE=0.1, DECIDE_BUCKET_CAPACITY=3):
            self.client.logout()
            Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
            FeatureFlag.objects.create(
                team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user
            )
            FeatureFlag.objects.create(
                team=self.team,
                filters={"groups": [{"properties": [], "rollout_percentage": None}]},
                name="This is a feature flag with default params, no filters.",
                key="default-flag",
                created_by=self.user,
            )  # Should be enabled for everyone

            for i in range(3):
                response = self._post_decide(api_version=i + 1)
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_replenish_over_time(self, *args):
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="y", DECIDE_BUCKET_REPLENISH_RATE=1, DECIDE_BUCKET_CAPACITY=1):
            self.client.logout()
            Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
            FeatureFlag.objects.create(
                team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user
            )
            FeatureFlag.objects.create(
                team=self.team,
                filters={"groups": [{"properties": [], "rollout_percentage": None}]},
                name="This is a feature flag with default params, no filters.",
                key="default-flag",
                created_by=self.user,
            )  # Should be enabled for everyone

            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 429)

            # wait for bucket to replenish
            time.sleep(1)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 429)

    def test_rate_limits_work_with_invalid_tokens(self, *args):
        self.client.logout()
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="y", DECIDE_BUCKET_REPLENISH_RATE=0.01, DECIDE_BUCKET_CAPACITY=3):
            for _ in range(3):
                response = self._post_decide(api_version=3, data={"token": "aloha?", "distinct_id": "123"})
                self.assertEqual(response.status_code, 401)

            response = self._post_decide(api_version=3, data={"token": "aloha?", "distinct_id": "123"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_work_with_missing_tokens(self, *args):
        self.client.logout()
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="y", DECIDE_BUCKET_REPLENISH_RATE=0.1, DECIDE_BUCKET_CAPACITY=3):
            for _ in range(3):
                response = self._post_decide(api_version=3, data={"distinct_id": "123"})
                self.assertEqual(response.status_code, 401)

            response = self._post_decide(api_version=3, data={"distinct_id": "123"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_work_with_malformed_request(self, *args):
        self.client.logout()
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="y", DECIDE_BUCKET_REPLENISH_RATE=0.1, DECIDE_BUCKET_CAPACITY=4):

            def invalid_request():
                return self.client.post("/decide/", {"data": "1==1"}, HTTP_ORIGIN="http://127.0.0.1:8000")

            for _ in range(4):
                response = invalid_request()
                self.assertEqual(response.status_code, 400)

            response = invalid_request()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_dont_apply_when_disabled(self, *args):
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="n"):
            self.client.logout()

            for _ in range(3):
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 200)

    def test_rate_limits_dont_mix_teams(self, *args):
        new_token = "bazinga"
        Team.objects.create(
            organization=self.organization,
            api_token=new_token,
            test_account_filters=[
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
            ],
        )
        self.client.logout()
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="y", DECIDE_BUCKET_REPLENISH_RATE=0.1, DECIDE_BUCKET_CAPACITY=3):

            for _ in range(3):
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 429)

            # other team is fine
            for _ in range(3):
                response = self._post_decide(api_version=3, data={"token": new_token, "distinct_id": "123"})
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=3, data={"token": new_token, "distinct_id": "other id"})
            self.assertEqual(response.status_code, 429)


class TestDatabaseCheckForDecide(BaseTest, QueryMatchingTest):
    """
    Tests that the database check for decide works as expected.
    Does not patch it.
    """

    def setUp(self, *args):
        cache.clear()

        is_postgres_connected_cached_check.cache_clear()

        super().setUp()
        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(
        self,
        data=None,
        origin="http://127.0.0.1:8000",
        api_version=1,
        distinct_id="example_id",
        groups={},
        geoip_disable=False,
        ip="127.0.0.1",
    ):
        return self.client.post(
            f"/decide/?v={api_version}",
            {
                "data": self._dict_to_b64(
                    data
                    or {
                        "token": self.team.api_token,
                        "distinct_id": distinct_id,
                        "groups": groups,
                        "geoip_disable": geoip_disable,
                    },
                )
            },
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    def _update_team(self, data):
        # use a non-csrf client to make requests
        client = Client()
        client.force_login(self.user)

        response = client.patch("/api/projects/@current/", data, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        client.logout()

    def test_database_check_doesnt_interfere_with_regular_computation(self, *args):
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=[
                "a",
                "{'id': 33040, 'shopify_domain': 'xxx.myshopify.com', 'shopify_token': 'shpat_xxxx', 'created_at': '2023-04-17T08:55:34.624Z', 'updated_at': '2023-04-21T08:43:34.479'}",
                "{'x': 'y'}",
                '{"x": "z"}',
            ],
            properties={"email": "tim@posthog.com", "realm": "cloud"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
            name="This is a group-based flag",
            key="random-flag",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=100,
            name="Filter by property",
            key="filer-by-property",
            created_by=self.user,
        )

        # one extra query to select 1 to check db is alive
        # one extra query to select team because not in cache
        with self.assertNumQueries(6):
            response = self._post_decide(api_version=3, distinct_id=12345)
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True, "filer-by-property": False})

        with self.assertNumQueries(4):
            response = self._post_decide(
                api_version=3,
                distinct_id={
                    "id": 33040,
                    "shopify_domain": "xxx.myshopify.com",
                    "shopify_token": "shpat_xxxx",
                    "created_at": "2023-04-17T08:55:34.624Z",
                    "updated_at": "2023-04-21T08:43:34.479",
                },
            )
            self.assertEqual(response.json()["featureFlags"], {"random-flag": True, "filer-by-property": True})

    def test_decide_doesnt_error_out_when_database_is_down_and_database_check_isnt_cached(self, *args):
        ALL_TEAM_PARAMS_FOR_DECIDE = {
            "session_recording_opt_in": True,
            "capture_console_log_opt_in": True,
            "inject_web_apps": True,
            "recording_domains": ["https://*.example.com"],
            "capture_performance_opt_in": True,
        }
        self._update_team(ALL_TEAM_PARAMS_FOR_DECIDE)
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=100,
            name="Filter by property",
            key="filer-by-property",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": []},
            rollout_percentage=100,
            name="Filter by property",
            key="no-props",
            created_by=self.user,
        )
        # populate redis caches
        self._post_decide(api_version=3, origin="https://random.example.com")

        # remove database check cache values
        is_postgres_connected_cached_check.cache_clear()

        with connection.execute_wrapper(QueryTimeoutWrapper()), snapshot_postgres_queries_context(
            self
        ), self.assertNumQueries(4):
            response = self._post_decide(api_version=3, origin="https://random.example.com").json()
            response = self._post_decide(api_version=3, origin="https://random.example.com").json()
            response = self._post_decide(api_version=3, origin="https://random.example.com").json()

            self.assertEqual(is_postgres_connected_cached_check.cache_info().hits, 2)
            self.assertEqual(is_postgres_connected_cached_check.cache_info().misses, 1)

            self.assertEqual(
                response["sessionRecording"],
                {"endpoint": "/s/", "recorderVersion": "v1", "consoleLogRecordingEnabled": True},
            )
            self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])
            self.assertEqual(response["siteApps"], [])
            self.assertEqual(response["capturePerformance"], True)
            self.assertEqual(response["featureFlags"], {"no-props": True})
            self.assertEqual(response["errorsWhileComputingFlags"], True)
