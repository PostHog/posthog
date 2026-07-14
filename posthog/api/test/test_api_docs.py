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

    @parameterized.expand(
        [
            # A CRLF payload used to reach the Content-Disposition header and trip Django's
            # BadHeaderError, surfacing as a 500. The version must now be ignored.
            ("crlf_injection", "1.0\r\nX-Injected: 1"),
            ("control_char", "1.0\nfoo"),
            ("too_long", "v" * 100),
            ("unsafe_chars", "1.0; drop"),
        ]
    )
    def test_unsafe_version_param_is_ignored(self, _name: str, version: str) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/", {"version": version})

        assert schema_response.status_code == 200
        # Nothing attacker-controlled leaks into the header, and it stays a single line.
        content_disposition = schema_response.headers.get("Content-Disposition", "")
        assert "\n" not in content_disposition
        assert "\r" not in content_disposition
        assert "X-Injected" not in content_disposition

    def test_safe_version_param_is_used_in_filename(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/", {"version": "1.0"})

        assert schema_response.status_code == 200
        assert "(1.0)" in schema_response.headers.get("Content-Disposition", "")

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
