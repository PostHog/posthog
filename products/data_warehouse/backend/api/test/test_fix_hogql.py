from posthog.test.base import APIBaseTest
from unittest import mock

from products.data_warehouse.backend.hogql_fixer_ai import HogQLQueryFixerTool


class TestFixHogQL(APIBaseTest):
    def test_create(self):
        with (
            mock.patch("products.data_warehouse.backend.hogql_fixer_ai.ChatOpenAI"),
            mock.patch.object(HogQLQueryFixerTool, "_parse_output", return_value="select timestamp from events"),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/fix_hogql/",
                {"query": "select timestam from events", "error": "Unable to resolve field: timestam"},
            )

            assert response.status_code == 200
