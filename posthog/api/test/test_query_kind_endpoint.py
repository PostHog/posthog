from posthog.test.base import APIBaseTest

from parameterized import parameterized


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
