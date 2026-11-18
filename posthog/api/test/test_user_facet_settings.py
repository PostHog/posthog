from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.user_facet_settings import UserFacetSettingsEntrySerializer
from posthog.models import Organization, UserFacetSettings
from posthog.models.scoping import team_scope
from posthog.test.id_jag import id_jag_access_token


class TestUserFacetSettingsEntrySerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing_key", {"source_type": "attribute"}, "key"),
            ("missing_source_type", {"key": "http.status_code"}, "source_type"),
            ("invalid_source_type", {"key": "http.status_code", "source_type": "column"}, "source_type"),
        ]
    )
    def test_rejects_invalid_entries(self, _name, data, invalid_field):
        serializer = UserFacetSettingsEntrySerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(invalid_field, serializer.errors)


class TestUserFacetSettingsAPI(APIBaseTest):
    def test_id_jag_token_cannot_write_another_organizations_current_project(self) -> None:
        token = id_jag_access_token(self.user, self.organization, "user:write")
        _, _, other_team = Organization.objects.bootstrap(self.user)
        self.user.current_team = other_team
        self.user.save()
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.patch("/api/user_facet_settings/@me/?product=logs", {"custom_facets": []}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        with team_scope(other_team.id):
            self.assertFalse(UserFacetSettings.objects.filter(user=self.user, team_id=other_team.id).exists())

    def test_missing_product_query_param_returns_400(self):
        response = self.client.get("/api/user_facet_settings/@me/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_defaults_to_empty_list(self):
        response = self.client.get("/api/user_facet_settings/@me/?product=logs")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"custom_facets": []})

    def test_update_is_scoped_per_product(self):
        payload = {"custom_facets": [{"key": "http.status_code", "source_type": "attribute"}]}

        response = self.client.patch(
            "/api/user_facet_settings/@me/?product=tracing",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"custom_facets": payload["custom_facets"]})

        # A different product for the same user/team stays untouched — the real regression risk
        # here is the product filter being dropped from the underlying update_or_create.
        logs_response = self.client.get("/api/user_facet_settings/@me/?product=logs")
        self.assertEqual(logs_response.json(), {"custom_facets": []})

        with team_scope(self.team.id, canonical=True):
            stored = UserFacetSettings.objects.get(user=self.user, team=self.team, product="tracing")
        self.assertEqual(stored.custom_facets, payload["custom_facets"])
