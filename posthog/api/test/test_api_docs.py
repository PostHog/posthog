from posthog.test.base import APIBaseTest


class TestAPIDocsSchema(APIBaseTest):
    def test_can_generate_api_docs_schema(self) -> None:
        self.client.logout()
        schema_response = self.client.get("/api/schema/")
        assert schema_response.status_code == 200
        # the response does have data, but mypy doesn't know that
        assert isinstance(schema_response.data, dict)  # type: ignore
        assert schema_response.headers.get("Content-Type") == "application/vnd.oai.openapi; charset=utf-8"
        assert int(str(schema_response.headers.get("Content-Length"))) > 0
