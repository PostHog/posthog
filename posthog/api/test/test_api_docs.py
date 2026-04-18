import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from posthog.models.cohort import Cohort


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
        # FunnelSerializer is declared in insight_serializers.py but not wired to any viewset,
        # so it doesn't appear in the generated /api/schema/ output. A serializer-level check
        # is therefore the right guard against this class of bug (default not in enum choices).
        from posthog.api.insight_serializers import FunnelSerializer

        field = FunnelSerializer().fields["funnel_window_interval_type"]
        assert field.default in field.choices, (
            f"funnel_window_interval_type default {field.default!r} is not in choices {list(field.choices)!r}. "
            f"Regression of #18673."
        )

    def test_week_start_day_schema_does_not_include_null_in_enum(self) -> None:
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


class TestCohortPersonsEndpointShape(ClickhouseTestMixin, APIBaseTest):
    """Integration test: assert the cohort persons endpoint response matches its documented schema shape."""

    def test_endpoint_response_matches_documented_schema(self) -> None:
        # Create a static cohort with one matching person so we can assert on the response shape.
        person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["test-user-1"],
            properties={"email": "alice@example.com"},
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test cohort",
            groups=[{"properties": [{"key": "email", "value": "alice@example.com", "type": "person"}]}],
            is_static=True,
        )
        cohort.insert_users_list_by_uuid(items=[str(person.uuid)], team_id=self.team.pk)

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort.id}/persons/")
        assert response.status_code == 200, response.content
        body = response.json()

        # Top-level shape must match CohortPersonsResponseSerializer
        assert set(body.keys()) >= {"results", "next", "previous"}, (
            f"Missing documented top-level keys. Got: {set(body.keys())!r}"
        )

        # Each result must carry the fields promised by CohortPersonResultSerializer.
        assert len(body["results"]) >= 1, "Expected at least one person in the cohort"
        documented_fields = {"id", "uuid", "type", "name", "distinct_ids", "properties", "created_at", "is_identified"}
        actual_fields = set(body["results"][0].keys())
        missing = documented_fields - actual_fields
        assert not missing, (
            f"Response is missing fields the schema promises: {missing!r}. "
            f"Actual fields: {actual_fields!r}. "
            f"Regression of #18673 — keep CohortPersonResultSerializer in sync with actor_base_query.SerializedPerson."
        )
