from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.customer_analytics.backend.test.factories import create_account


class TestAccountSqlQuery(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    @parameterized.expand(["example-account", "example-'quoted-account"])
    def test_query_filters_by_account_external_id(self, external_id: str) -> None:
        create_account(team_id=self.team.id, name="Example account", external_id=external_id)
        create_account(team_id=self.team.id, name="Other account", external_id="other-account")

        response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT * FROM system.accounts WHERE external_id = {account_external_id}",
                    "values": {"account_external_id": external_id},
                }
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert [row[data["columns"].index("name")] for row in data["results"]] == ["Example account"]
        assert [row[data["columns"].index("external_id")] for row in data["results"]] == [external_id]

    def test_query_error_metadata_keeps_placeholder_values(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "SELECT missing_account_field FROM system.accounts WHERE external_id = {account_external_id}",
                    "values": {"account_external_id": "example-account"},
                }
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        metadata = response.json()["extra"]["hogql_metadata"]
        assert metadata["isValid"] is False
        assert not metadata.get("internalError", False), metadata
        assert any("missing_account_field" in error["message"] for error in metadata["errors"]), metadata
