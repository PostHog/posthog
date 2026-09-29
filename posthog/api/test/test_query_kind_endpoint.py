from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestQueryKindEndpoint(APIBaseTest):
    @parameterized.expand(
        [
            ("environment", "/api/environments/{team_id}/query/HogQLQuery/"),
            ("project", "/api/projects/{team_id}/query/HogQLQuery/"),
        ]
    )
    def test_query_kind_endpoint_accepts_post(self, _name: str, url_template: str) -> None:
        response = self.client.post(
            url_template.format(team_id=self.team.pk),
            {"query": {"kind": "HogQLQuery", "query": "select 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    @parameterized.expand(
        [
            ("environment", "/api/environments/{team_id}/query/HogQLQuery/"),
            ("project", "/api/projects/{team_id}/query/HogQLQuery/"),
            # digit-containing kind — the route regex used to reject these with a 405
            ("environment_digit_kind", "/api/environments/{team_id}/query/PathsV2Query/"),
        ]
    )
    def test_query_kind_endpoint_rejects_mismatch(self, _name: str, url_template: str) -> None:
        response = self.client.post(
            url_template.format(team_id=self.team.pk),
            {"query": {"kind": "EventsQuery"}},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Query kind mismatch", response.json().get("detail", ""))

    @parameterized.expand(
        [
            ("environment", "/api/environments/{team_id}/query/upgrade/"),
            ("project", "/api/projects/{team_id}/query/upgrade/"),
        ]
    )
    def test_reserved_query_routes_are_not_treated_as_query_kind(self, _name: str, url_template: str) -> None:
        response = self.client.post(
            url_template.format(team_id=self.team.pk),
            {"query": {"kind": "HogQLQuery", "query": "select 1"}},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    @parameterized.expand(
        [
            ("query_scope_allows_plain_kind", ["query:read"], {"kind": "HogQLQuery", "query": "select 1"}, 200),
            ("kind_scope_still_required", ["query:read"], {"kind": "ErrorTrackingReleasesQuery"}, 403),
        ]
    )
    def test_query_kind_endpoint_with_personal_api_key(
        self, _name: str, scopes: list[str], query: dict, expected_status: int
    ) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="query kind", user=self.user, secure_value=hash_key_value(value), scopes=scopes
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/query/{query['kind']}/",
            {"query": query},
            format="json",
            headers={"Authorization": f"Bearer {value}"},
        )

        self.assertEqual(response.status_code, expected_status, response.content)
