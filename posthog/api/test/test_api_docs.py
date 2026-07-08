from posthog.test.base import APIBaseTest

from parameterized import parameterized


class TestAPIDocsSchema(APIBaseTest):
    def test_can_generate_api_docs_schema(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        # the response does have data, but mypy doesn't know that
        assert isinstance(schema_response.data, dict)
        assert schema_response.headers.get("Content-Type") == "application/vnd.oai.openapi; charset=utf-8"
        assert int(str(schema_response.headers.get("Content-Length"))) > 0

    @parameterized.expand(["swagger-ui", "redoc"])
    def test_api_docs_ui_renders(self, ui_path: str) -> None:
        # Guards the drf-spectacular HTML docs UIs against render-time 500s (e.g. a
        # dependency bump or SPECTACULAR_SETTINGS change breaking the template). The
        # schema endpoint above only exercises the JSON, never these template renders.
        self.client.logout()

        response = self.client.get(f"/api/schema/{ui_path}/", HTTP_ACCEPT="text/html")

        assert response.status_code == 200
        assert str(response.headers.get("Content-Type")).startswith("text/html")
        assert b"/api/schema/" in response.content

    def test_llm_prompt_schema_includes_search_and_prompt_name_path_param(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        assert isinstance(schema_response.data, dict)

        paths = schema_response.data["paths"]
        list_operation = paths["/api/projects/{project_id}/llm_prompts/"]["get"]
        list_params = list_operation.get("parameters", [])
        assert any(param.get("in") == "query" and param.get("name") == "search" for param in list_params)
        assert any(param.get("in") == "query" and param.get("name") == "content" for param in list_params)

        by_name_path = "/api/projects/{project_id}/llm_prompts/name/{prompt_name}/"
        assert by_name_path in paths

        for method in ("get", "patch"):
            method_params = paths[by_name_path][method].get("parameters", [])
            assert any(param.get("in") == "path" and param.get("name") == "prompt_name" for param in method_params)
            assert not any(param.get("name") == "name" for param in method_params)
