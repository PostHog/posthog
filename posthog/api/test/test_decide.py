import base64
import json

from posthog.models import FeatureFlag, Person, PersonalAPIKey

from .base import BaseTest


class TestDecide(BaseTest):
    TESTS_API = True

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(self, data=None, origin="http://127.0.0.1:8000"):
        return self.client.post(
            "/decide/",
            {"data": self._dict_to_b64(data or {"token": self.team.api_token, "distinct_id": "example_id"})},
            HTTP_ORIGIN=origin,
        ).json()

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
        self.assertIsNone(response.get("toolbarVersion", None))

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
        response = self._post_decide()
        self.assertEqual(response["sessionRecording"], False)

        self.team.session_recording_opt_in = True
        self.team.save()

        response = self._post_decide()
        self.assertEqual(response["sessionRecording"], {"endpoint": "/s/"})
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js", "lz64"])

    def test_user_session_recording_evil_site(self):
        self.team.app_urls = ["https://example.com"]
        self.team.session_recording_opt_in = True
        self.team.save()

        response = self._post_decide(origin="evil.site.com")
        self.assertEqual(response["sessionRecording"], False)

        response = self._post_decide(origin="https://example.com")
        self.assertEqual(response["sessionRecording"], {"endpoint": "/s/"})

    def test_feature_flags(self):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key="beta-feature", created_by=self.user,
        )

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
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=50,
            name="Filter by property 2",
            key="filer-by-property-2",
            created_by=self.user,
        )
        with self.assertNumQueries(5):
            response = self._post_decide()
        self.assertEqual(response["featureFlags"][0], "beta-feature")

        with self.assertNumQueries(5):
            response = self._post_decide({"token": self.team.api_token, "distinct_id": "another_id"})
        self.assertEqual(len(response["featureFlags"]), 0)

    def test_feature_flags_with_personal_api_key(self):
        key = PersonalAPIKey(label="X", user=self.user)
        key.save()
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=100, name="Test", key="test", created_by=self.user,
        )
        response = self._post_decide({"distinct_id": "example_id", "api_key": key.value, "project_id": self.team.id})
        self.assertEqual(len(response["featureFlags"]), 1)
