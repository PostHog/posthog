import pytest
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
        assert schema_response.headers.get("Content-Type") == "application/vnd.oai.openapi; charset=utf-8"
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

    def test_llm_prompt_schema_includes_search_and_prompt_name_path_param(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        assert isinstance(schema_response.data, dict)

        paths = schema_response.data["paths"]
        list_operation = paths["/api/environments/{project_id}/llm_prompts/"]["get"]
        list_params = list_operation.get("parameters", [])
        assert any(param.get("in") == "query" and param.get("name") == "search" for param in list_params)

        by_name_path = "/api/environments/{project_id}/llm_prompts/name/{prompt_name}/"
        assert by_name_path in paths

        for method in ("get", "patch"):
            method_params = paths[by_name_path][method].get("parameters", [])
            assert any(param.get("in") == "path" and param.get("name") == "prompt_name" for param in method_params)
            assert not any(param.get("name") == "name" for param in method_params)
