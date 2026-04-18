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
        assert any(param.get("in") == "query" and param.get("name") == "content" for param in list_params)

        by_name_path = "/api/environments/{project_id}/llm_prompts/name/{prompt_name}/"
        assert by_name_path in paths

        for method in ("get", "patch"):
            method_params = paths[by_name_path][method].get("parameters", [])
            assert any(param.get("in") == "path" and param.get("name") == "prompt_name" for param in method_params)
            assert not any(param.get("name") == "name" for param in method_params)

    def test_cohort_persons_endpoint_has_paginated_persons_response_schema(self) -> None:
        """
        Regression test for #18673: the cohort persons endpoint returns a paginated list of Person
        objects, but the generated schema previously inherited the viewset's default Cohort response.
        """
        self.client.logout()

        schema_response = self.client.get("/api/schema/")
        assert schema_response.status_code == 200
        assert isinstance(schema_response.data, dict)

        paths = schema_response.data["paths"]
        persons_path = "/api/projects/{project_id}/cohorts/{id}/persons/"
        assert persons_path in paths

        get_op = paths[persons_path]["get"]

        # Query params `limit` and `offset` must be documented.
        params = get_op.get("parameters", [])
        param_names = {p.get("name") for p in params if p.get("in") == "query"}
        assert "limit" in param_names
        assert "offset" in param_names

        # Response must be a paginated Person list, not a single Cohort.
        response_ref = get_op["responses"]["200"]["content"]["application/json"]["schema"].get("$ref", "")
        assert response_ref.endswith("/CohortPersonsResponse"), (
            f"Expected CohortPersonsResponse schema, got {response_ref}. "
            f"Regression of #18673 — the cohort persons endpoint must advertise its paginated Person response."
        )

        response_schema = schema_response.data["components"]["schemas"]["CohortPersonsResponse"]
        assert "results" in response_schema["properties"]
        assert "next" in response_schema["properties"]
        assert "previous" in response_schema["properties"]

    def test_funnel_window_interval_type_default_matches_enum(self) -> None:
        """
        Regression test for #18673: the default value must be one of the enum choices.
        OpenAPI generators fail on `default: "days"` when the enum is `["DAY", "HOUR", ...]`.
        Asserted against both the serializer (direct) and the generated schema (integration).
        """
        from posthog.api.insight_serializers import FunnelSerializer

        # Direct serializer check — catches accidental reverts at the source
        field = FunnelSerializer().fields["funnel_window_interval_type"]
        assert field.default in field.choices, (
            f"funnel_window_interval_type default {field.default!r} is not in choices {list(field.choices)!r}. "
            f"Regression of #18673."
        )

        # Schema-level check — catches drf-spectacular regressions too
        self.client.logout()
        schema_response = self.client.get("/api/schema/")
        assert schema_response.status_code == 200

        schemas = schema_response.data.get("components", {}).get("schemas", {})
        funnel_schema_key = next((k for k in schemas if k.startswith("Funnel") and "properties" in schemas[k]), None)
        if funnel_schema_key:
            interval_type = schemas[funnel_schema_key]["properties"].get("funnel_window_interval_type")
            if interval_type and "default" in interval_type and "enum" in interval_type:
                assert interval_type["default"] in interval_type["enum"], (
                    f"Generated schema default {interval_type['default']!r} not in enum {interval_type['enum']!r}"
                )

    def test_week_start_day_schema_does_not_include_null_in_enum(self) -> None:
        """
        Regression test for #18673: `null` must NOT appear inside the enum for nullable fields.
        OpenAPI 3.0 uses `nullable: true` as a separate attribute — a `null` value inside an
        integer enum is invalid and breaks many client generators (reported by @kamranayub).
        """
        self.client.logout()

        schema_response = self.client.get("/api/schema/")
        assert schema_response.status_code == 200

        schemas = schema_response.data.get("components", {}).get("schemas", {})
        # TeamSerializer is registered as "Team" in the generated schema
        team_schema = schemas.get("Team") or schemas.get("TeamSerializer") or {}
        week_start_day = team_schema.get("properties", {}).get("week_start_day", {})

        if "enum" in week_start_day:
            assert None not in week_start_day["enum"], (
                f"week_start_day enum contains null: {week_start_day['enum']!r}. "
                f"Use `nullable: true` as a separate attribute instead. Regression of #18673."
            )
