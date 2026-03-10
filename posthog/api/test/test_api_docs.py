import pytest
from parameterized import parameterized

from posthog.test.base import APIBaseTest


class TestAPIDocsSchema(APIBaseTest):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, capsys, snapshot):
        self._capsys = capsys
        self._snapshot = snapshot

    def test_can_generate_api_docs_schema(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        # the response does have data, but mypy doesn't know that
        assert isinstance(schema_response.data, dict)
        assert (
            schema_response.headers.get("Content-Type")
            == "application/vnd.oai.openapi; charset=utf-8"
        )
        assert int(str(schema_response.headers.get("Content-Length"))) > 0

    def test_api_docs_generation_warnings_snapshot(self) -> None:
        """
        There are a little under 200 warning from API docs generation. Lets at least not add more.
        """
        self.client.logout()

        self.client.get("/api/schema/")

        # we log lots of warnings when generating the schema
        warnings = self._capsys.readouterr().err.split("\n")
        assert sorted(warnings) == self._snapshot

    def _get_cohort_persons_response_properties(self) -> dict:
        self.client.logout()
        schema_response = self.client.get("/api/schema/")
        assert schema_response.status_code == 200
        openapi_schema = schema_response.data
        response_schema = openapi_schema["paths"][
            "/api/projects/{project_id}/cohorts/{id}/persons/"
        ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        while "$ref" in response_schema:
            schema_name = response_schema["$ref"].split("/")[-1]
            response_schema = openapi_schema["components"]["schemas"][schema_name]
        return response_schema.get("properties", {})

    @parameterized.expand(
        [
            ("results",),
            ("next",),
            ("previous",),
        ]
    )
    def test_cohort_persons_endpoint_schema_has_pagination_field(
        self, field: str
    ) -> None:
        properties = self._get_cohort_persons_response_properties()
        assert field in properties
