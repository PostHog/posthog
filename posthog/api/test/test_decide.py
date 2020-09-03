import base64
import json
from unittest.mock import patch

from posthog.models import FeatureFlag, Person

from .base import BaseTest


class TestDecide(BaseTest):
    TESTS_API = True

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def test_user_on_own_site_enabled(self):
        user = self.team.users.all()[0]
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com/maybesubdomain"]
        self.team.save()
        response = self.client.get("/decide/", HTTP_ORIGIN="https://example.com").json()
        self.assertEqual(response["isAuthenticated"], True)
        self.assertEqual(response["editorParams"]["toolbarVersion"], "toolbar")

    def test_user_on_own_site_disabled(self):
        user = self.team.users.all()[0]
        user.toolbar_mode = "default"
        user.save()

        self.team.app_urls = ["https://example.com/maybesubdomain"]
        self.team.save()
        response = self.client.get("/decide", HTTP_ORIGIN="https://example.com").json()
        self.assertEqual(response["isAuthenticated"], True)
        self.assertIsNone(response.get("toolbarVersion", None))

    def test_user_on_evil_site(self):
        user = self.team.users.all()[0]
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        response = self.client.get("/decide/", HTTP_ORIGIN="https://evilsite.com").json()
        self.assertEqual(response["isAuthenticated"], False)
        self.assertIsNone(response["editorParams"].get("toolbarVersion", None))

    def test_user_on_local_host(self):
        user = self.team.users.all()[0]
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        response = self.client.get("/decide", HTTP_ORIGIN="http://127.0.0.1:8000").json()
        self.assertEqual(response["isAuthenticated"], True)
        self.assertEqual(response["editorParams"]["toolbarVersion"], "toolbar")

    @patch("posthog.models.team.TEAM_CACHE", {})
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
        with self.assertNumQueries(4):
            response = self.client.post(
                "/decide/",
                {"data": self._dict_to_b64({"token": self.team.api_token, "distinct_id": "example_id"})},
                HTTP_ORIGIN="http://127.0.0.1:8000",
            ).json()
        self.assertEqual(response["featureFlags"][0], "beta-feature")

        with self.assertNumQueries(3):  # Caching of teams saves 1 query
            response = self.client.post(
                "/decide/",
                {"data": self._dict_to_b64({"token": self.team.api_token, "distinct_id": "another_id"})},
                HTTP_ORIGIN="http://127.0.0.1:8000",
            ).json()
        self.assertEqual(len(response["featureFlags"]), 0)
