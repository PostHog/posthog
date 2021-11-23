import base64
import json

from django.test.client import Client
from rest_framework import status

from posthog.models import FeatureFlag, GroupTypeMapping, Person, PersonalAPIKey
from posthog.models.feature_flag import FeatureFlagOverride
from posthog.test.base import BaseTest


class TestDecide(BaseTest):
    """
    Tests the `/decide` endpoint.
    We use Django's base test class instead of DRF's because we need granular control over the Content-Type sent over.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(
        self, data=None, origin="http://127.0.0.1:8000", api_version=1, distinct_id="example_id", groups={}
    ):
        return self.client.post(
            f"/decide/?v={api_version}",
            {
                "data": self._dict_to_b64(
                    data or {"token": self.team.api_token, "distinct_id": distinct_id, "groups": groups}
                )
            },
            HTTP_ORIGIN=origin,
        )

    def test_user_on_own_site_enabled(self):
        user = self.organization.members.first()
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com/maybesubdomain"]
        self.team.save()
        response = self.client.get("/decide/", HTTP_ORIGIN="https://example.com").json()
        self.assertEqual(response["isAuthenticated"], True)
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])
        self.assertEqual(response["editorParams"]["toolbarVersion"], "toolbar")

    def test_user_on_own_site_disabled(self):
        user = self.organization.members.first()
        user.toolbar_mode = "disabled"
        user.save()

        self.team.app_urls = ["https://example.com/maybesubdomain"]
        self.team.save()

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.get("/decide", HTTP_ORIGIN="https://example.com").json()
        self.assertEqual(response["isAuthenticated"], True)
        self.assertIsNone(response["editorParams"].get("toolbarVersion"))

    def test_user_on_evil_site(self):
        user = self.organization.members.first()
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        response = self.client.get("/decide/", HTTP_ORIGIN="https://evilsite.com").json()
        self.assertEqual(response["isAuthenticated"], False)
        self.assertIsNone(response["editorParams"].get("toolbarVersion", None))

    def test_user_on_local_host(self):
        user = self.organization.members.first()
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        response = self.client.get("/decide", HTTP_ORIGIN="http://127.0.0.1:8000").json()
        self.assertEqual(response["isAuthenticated"], True)
        self.assertEqual(response["sessionRecording"], False)
        self.assertEqual(response["editorParams"]["toolbarVersion"], "toolbar")
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])

    def test_user_session_recording_opt_in(self):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self.team.session_recording_opt_in = True
        self.team.save()

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], {"endpoint": "/s/"})
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])

    def test_user_session_recording_opt_in_wildcard_domain(self):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self.team.session_recording_opt_in = True
        self.team.app_urls = ["https://*.example.com"]
        self.team.save()

        response = self._post_decide(origin="https://random.example.com").json()
        self.assertEqual(response["sessionRecording"], {"endpoint": "/s/"})
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])

        # Make sure the domain matches exactly
        response = self._post_decide(origin="https://random.example.com.evilsite.com").json()
        self.assertEqual(response["sessionRecording"], False)

    def test_user_session_recording_evil_site(self):
        self.team.app_urls = ["https://example.com"]
        self.team.session_recording_opt_in = True
        self.team.save()

        response = self._post_decide(origin="evil.site.com").json()
        self.assertEqual(response["sessionRecording"], False)

        response = self._post_decide(origin="https://example.com").json()
        self.assertEqual(response["sessionRecording"], {"endpoint": "/s/"})

    def test_feature_flags(self):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user,
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

        with self.assertNumQueries(5):
            response = self._post_decide()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("default-flag", response.json()["featureFlags"])
        self.assertIn("beta-feature", response.json()["featureFlags"])
        self.assertIn("filer-by-property-2", response.json()["featureFlags"])

        with self.assertNumQueries(5):
            response = self._post_decide({"token": self.team.api_token, "distinct_id": "another_id"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["featureFlags"], ["default-flag"])

    def test_feature_flags_v2(self):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user,
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
                    ],
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        with self.assertNumQueries(3):
            response = self._post_decide(api_version=1)  # v1 functionality should not break
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertIn("beta-feature", response.json()["featureFlags"])
            self.assertIn("default-flag", response.json()["featureFlags"])

        with self.assertNumQueries(3):
            response = self._post_decide(api_version=2)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        with self.assertNumQueries(3):
            response = self._post_decide(api_version=2, distinct_id="other_id")
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "third-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # different hash, different variant assigned

    def test_feature_flags_v2_complex(self):
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
                    ],
                },
            },
            name="This is a feature flag with top-level property filtering and percentage rollout.",
            key="multivariate-flag",
            created_by=self.user,
        )

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

    def test_feature_flags_v2_override(self):
        self.user.distinct_id = "static-distinct-id"
        self.user.save()
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=[self.user.distinct_id, "not-canonical-distinct-id"],
            properties={"email": self.user.email},
        )
        ff_1 = FeatureFlag.objects.create(
            team=self.team,
            name="Full rollout feature",
            rollout_percentage=100,
            key="bool-key-overridden-to-false",
            created_by=self.user,
        )  # Overriden to False

        ff_2 = FeatureFlag.objects.create(
            team=self.team,
            name="Zero rollout feature",
            rollout_percentage=0,
            key="bool-key-overridden-to-true",
            created_by=self.user,
        )  # Overriden to True

        ff_3 = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 100},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 0},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 0},
                    ],
                },
            },
            name="This is a multi var feature flag that gets overriden.",
            key="multivariate-flag-overridden",
            created_by=self.user,
        )  # Multi-var overriden to diff variant

        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {"key": "first-variant", "name": "First Variant", "rollout_percentage": 0},
                        {"key": "second-variant", "name": "Second Variant", "rollout_percentage": 100},
                        {"key": "third-variant", "name": "Third Variant", "rollout_percentage": 0},
                    ],
                },
            },
            name="This is a multi var feature flag that doens't get overriden.",
            key="multivariate-flag-not-overridden",
            created_by=self.user,
        )  # Multi-var not overriden

        FeatureFlag.objects.create(
            team=self.team,
            name="This is a feature flag with default params, no filters.",
            key="flag-rollout-100",
            rollout_percentage=100,
            created_by=self.user,
        )  # True feature flag, not overriden

        FeatureFlag.objects.create(
            team=self.team,
            name="This is a feature flag with default params, no filters.",
            key="flag-rollout-0",
            rollout_percentage=0,
            created_by=self.user,
        )  # False feature flag, not overriden

        FeatureFlagOverride.objects.create(
            team=self.team, user=self.user, feature_flag=ff_1, override_value=False,
        )
        FeatureFlagOverride.objects.create(
            team=self.team, user=self.user, feature_flag=ff_2, override_value=True,
        )
        FeatureFlagOverride.objects.create(
            team=self.team, user=self.user, feature_flag=ff_3, override_value="third-variant",
        )

        with self.assertNumQueries(3):
            response = self._post_decide(api_version=1, distinct_id=str(self.user.distinct_id))
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json()["featureFlags"],
                [
                    "multivariate-flag-overridden",
                    "multivariate-flag-not-overridden",
                    "flag-rollout-100",
                    "bool-key-overridden-to-true",
                ],
            )

        with self.assertNumQueries(3):
            response = self._post_decide(api_version=2, distinct_id=str(self.user.distinct_id))
            feature_flags_for_canonical_distinct_id = response.json()["featureFlags"]
            self.assertEqual(
                feature_flags_for_canonical_distinct_id,
                {
                    "bool-key-overridden-to-true": True,
                    "multivariate-flag-overridden": "third-variant",
                    "multivariate-flag-not-overridden": "second-variant",
                    "flag-rollout-100": True,
                },
            )
        # Ensure we get the same response from both of the user's distinct_ids
        with self.assertNumQueries(3):
            response_non_canonical_distinct_id = self._post_decide(
                api_version=2, distinct_id="not-canonical-distinct-id"
            )
            self.assertEqual(
                response_non_canonical_distinct_id.json()["featureFlags"], feature_flags_for_canonical_distinct_id,
            )

        with self.assertNumQueries(3):
            response = self._post_decide(api_version=2, distinct_id="user-with-no-overriden-flags")
            self.assertEqual(
                response.json()["featureFlags"],
                {
                    "bool-key-overridden-to-false": True,
                    "multivariate-flag-overridden": "first-variant",
                    "multivariate-flag-not-overridden": "second-variant",
                    "flag-rollout-100": True,
                },
            )

    def test_feature_flags_v2_with_groups(self):
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

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="example_id")
            self.assertEqual(response.json()["featureFlags"], {})

        with self.assertNumQueries(4):
            response = self._post_decide(api_version=2, distinct_id="example_id", groups={"organization": "foo"})
            self.assertEqual(response.json()["featureFlags"], {"groups-flag": True})

    def test_feature_flags_with_personal_api_key(self):
        key = PersonalAPIKey(label="X", user=self.user)
        key.save()
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Test", key="test", created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Disabled", key="disabled", created_by=self.user, active=False,
        )  # disabled flag
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="default-flag",
            created_by=self.user,
        )  # enabled for everyone
        response = self._post_decide(
            {"distinct_id": "example_id", "api_key": key.value, "project_id": self.team.id}
        ).json()
        self.assertEqual(response["featureFlags"], ["test", "default-flag"])

    def test_personal_api_key_without_project_id(self):
        key = PersonalAPIKey(label="X", user=self.user)
        key.save()
        Person.objects.create(team=self.team, distinct_ids=["example_id"])

        response = self._post_decide({"distinct_id": "example_id", "api_key": key.value})
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

    def test_missing_token(self):
        key = PersonalAPIKey(label="X", user=self.user)
        key.save()
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Test", key="test", created_by=self.user,
        )
        response = self._post_decide({"distinct_id": "example_id", "api_key": None, "project_id": self.team.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["featureFlags"], [])
        self.assertFalse(response_json["sessionRecording"])

    def test_invalid_payload_on_decide_endpoint(self):

        invalid_payloads = [base64.b64encode("1-1".encode("utf-8")).decode("utf-8"), "1==1", "{distinct_id-1}"]

        for payload in invalid_payloads:
            response = self.client.post("/decide/", {"data": payload}, HTTP_ORIGIN="http://127.0.0.1:8000")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            response_data = response.json()
            detail = response_data.pop("detail")
            self.assertEqual(
                response.json(), {"type": "validation_error", "code": "malformed_data", "attr": None},
            )
            self.assertIn("Malformed request data:", detail)

    def test_invalid_gzip_payload_on_decide_endpoint(self):

        response = self.client.post(
            "/decide/?compression=gzip",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03",
            HTTP_ORIGIN="http://127.0.0.1:8000",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        detail = response_data.pop("detail")
        self.assertEqual(
            response.json(), {"type": "validation_error", "code": "malformed_data", "attr": None},
        )
        self.assertIn("Malformed request data:", detail)
