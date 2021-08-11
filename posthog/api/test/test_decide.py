import base64
import json

from django.test.client import Client
from rest_framework import status

from posthog.models import FeatureFlag, Person, PersonalAPIKey
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

    def _post_decide(self, data=None, origin="http://127.0.0.1:8000"):
        return self.client.post(
            "/decide/",
            {"data": self._dict_to_b64(data or {"token": self.team.api_token, "distinct_id": "example_id"})},
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

        with self.assertNumQueries(4):
            response = self._post_decide()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("default-flag", response.json()["featureFlags"])
        self.assertIn("beta-feature", response.json()["featureFlags"])
        self.assertIn("filer-by-property-2", response.json()["featureFlags"])

        with self.assertNumQueries(4):
            response = self._post_decide({"token": self.team.api_token, "distinct_id": "another_id"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["featureFlags"], ["default-flag"])

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
