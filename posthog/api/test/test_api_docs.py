import os
import re

from posthog.test.base import APIBaseTest
from unittest import mock

from django.urls import URLPattern, path

from drf_spectacular.generators import SchemaGenerator
from parameterized import parameterized
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import extend_schema


class _XInternalMarkerSerializer(serializers.Serializer):
    ok = serializers.BooleanField(help_text="Always true.")


class _XInternalMarkerViewSet(viewsets.ViewSet):
    scope_object = "project"

    @extend_schema(responses={200: _XInternalMarkerSerializer}, extensions={"x-internal": True})
    def list(self, request: Request) -> Response:
        return Response({"ok": True})


@extend_schema(responses={200: _XInternalMarkerSerializer}, extensions={"x-internal": True})
class _XInternalClassMarkerViewSet(viewsets.ViewSet):
    scope_object = "project"

    def list(self, request: Request) -> Response:
        return Response({"ok": True})

    @extend_schema(description="Marker action with its own schema annotation.")
    @action(detail=False, methods=["GET"])
    def summary(self, request: Request) -> Response:
        return Response({"ok": True})


class TestAPIDocsSchema(APIBaseTest):
    def test_retired_project_environments_route_is_not_in_schema(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        assert isinstance(schema_response.data, dict)

        paths = schema_response.data["paths"]
        # The route 403s every request. Its viewset inherits every TeamViewSet action, so a hidden
        # viewset is the only thing keeping those actions out of the generated types and MCP tools
        assert not [p for p in paths if re.match(r"^/api/projects/[^/]+/environments/", p)]
        # The same action survives under the live project route
        assert any(p.endswith("/tracing_config/") for p in paths)

    @parameterized.expand(
        [
            (
                "method_annotation",
                [path("api/x_internal_marker/", _XInternalMarkerViewSet.as_view({"get": "list"}))],
            ),
            (
                "class_annotation_reaches_annotated_action",
                [
                    path("api/x_internal_class_marker/", _XInternalClassMarkerViewSet.as_view({"get": "list"})),
                    path(
                        "api/x_internal_class_marker/summary/",
                        _XInternalClassMarkerViewSet.as_view({"get": "summary"}),
                    ),
                ],
            ),
        ]
    )
    def test_x_internal_operations_are_only_in_the_codegen_schema(self, _name: str, patterns: list[URLPattern]) -> None:
        expected_paths = sorted(f"/{pattern.pattern}" for pattern in patterns)

        served_schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
        assert sorted(served_schema["paths"]) == []

        codegen_env = {"OPENAPI_INCLUDE_INTERNAL": "1", "OPENAPI_MOCK_INTERNAL_API_SECRET": "1"}
        with mock.patch.dict(os.environ, codegen_env):
            codegen_schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
        assert sorted(codegen_schema["paths"]) == expected_paths

    def test_can_generate_api_docs_schema(self) -> None:
        self.client.logout()

        schema_response = self.client.get("/api/schema/")

        assert schema_response.status_code == 200
        # the response does have data, but mypy doesn't know that
        assert isinstance(schema_response.data, dict)
        assert schema_response.headers.get("Content-Type") == "application/vnd.oai.openapi; charset=utf-8"
        assert int(str(schema_response.headers.get("Content-Length"))) > 0

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
