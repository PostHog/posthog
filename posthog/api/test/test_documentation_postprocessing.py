from typing import Any

import pytest

from posthog.api.documentation.postprocessing import custom_postprocessing_hook
from posthog.api.documentation.preprocessing import preprocess_exclude_path_format


class _Callback:
    def __init__(self, cls: type) -> None:
        self.cls = cls


def _view(module: str = "posthog.api.example", **attrs: Any) -> _Callback:
    return _Callback(type("ExampleViewSet", (), {"__module__": module, **attrs}))


def _operation(operation_id: str, **extra: Any) -> dict[str, Any]:
    return {"operationId": operation_id, "tags": [], **extra}


@pytest.mark.parametrize(
    "_name,attrs",
    [
        ("no_scope_object", {}),
        ("hidden", {"scope_object": "project", "hide_api_docs": True}),
        ("internal", {"scope_object": "INTERNAL"}),
        ("current_team_root", {"scope_object": "project", "param_derived_from_user_current_team": "team_id"}),
    ],
)
def test_preprocess_excludes_view(_name: str, attrs: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAPI_INCLUDE_INTERNAL", raising=False)
    endpoints = [("/api/projects/{parent_lookup_team_id}/things/", None, "GET", _view(**attrs))]

    assert preprocess_exclude_path_format(endpoints) == []


@pytest.mark.parametrize(
    "_name,attrs",
    [
        ("include_in_api_docs", {"include_in_api_docs": True}),
        ("internal_with_env_opt_in", {"scope_object": "INTERNAL"}),
        (
            "current_team_root_forced",
            {
                "scope_object": "project",
                "param_derived_from_user_current_team": "team_id",
                "force_include_in_api_docs": True,
            },
        ),
    ],
)
def test_preprocess_includes_view(_name: str, attrs: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAPI_INCLUDE_INTERNAL", "1")
    endpoints = [("/api/projects/{parent_lookup_team_id}/things/", None, "GET", _view(**attrs))]

    assert [e[0] for e in preprocess_exclude_path_format(endpoints)] == ["/api/projects/{project_id}/things/"]


def test_preprocess_and_postprocess_mark_duplicates_and_attribute_products() -> None:
    project_view = _view(scope_object="project")
    product_view = _view(module="products.surveys.backend.api", scope_object="project")
    endpoints = [
        ("/api/projects/{parent_lookup_team_id}/things/", None, "GET", project_view),
        ("/api/environments/{parent_lookup_team_id}/things/", None, "GET", project_view),
        ("/api/environments/{parent_lookup_team_id}/env_only/", None, "GET", project_view),
        ("/api/organizations/{parent_lookup_organization_id}/things/", None, "GET", project_view),
        ("/api/organizations/{parent_lookup_organization_id}/projects/", None, "GET", project_view),
        ("/api/projects/{parent_lookup_team_id}/surveys/{pk}/", None, "GET", product_view),
    ]

    paths = [e[0] for e in preprocess_exclude_path_format(endpoints)]

    assert paths == [
        "/api/projects/{project_id}/things/",
        "/api/environments/{environment_id}/things/",
        "/api/environments/{project_id}/env_only/",
        "/api/organizations/{organization_id}/things/",
        "/api/organizations/{organization_id}/projects/",
        "/api/projects/{project_id}/surveys/{pk}/",
    ]

    spec = {
        "paths": {
            "/api/projects/{project_id}/things/": {"get": _operation("projects_things_list")},
            "/api/environments/{environment_id}/things/": {"get": _operation("things_list")},
            "/api/environments/{project_id}/env_only/": {"get": _operation("environments_env_only_list")},
            "/api/organizations/{organization_id}/things/": {"get": _operation("organizations_things_list")},
            "/api/organizations/{organization_id}/projects/": {"get": _operation("organizations_projects_list")},
            "/api/projects/{project_id}/surveys/{id}/": {"get": _operation("projects_surveys_retrieve")},
        }
    }

    result = custom_postprocessing_hook(spec, generator=None, request=None, public=True)
    ops = {path: methods["get"] for path, methods in result["paths"].items()}

    assert {path: (op["operationId"], op.get("deprecated", False)) for path, op in ops.items()} == {
        "/api/projects/{project_id}/things/": ("things_list", False),
        "/api/environments/{environment_id}/things/": ("environments_things_list", True),
        "/api/environments/{project_id}/env_only/": ("env_only_list", False),
        "/api/organizations/{organization_id}/things/": ("org_organizations_things_list", True),
        "/api/organizations/{organization_id}/projects/": ("organizations_projects_list", False),
        "/api/projects/{project_id}/surveys/{id}/": ("surveys_retrieve", False),
    }
    assert ops["/api/projects/{project_id}/surveys/{id}/"]["x-product"] == ["surveys"]
    assert ops["/api/projects/{project_id}/surveys/{id}/"]["tags"] == ["surveys"]


@pytest.mark.parametrize(
    "_name,extra,expected_product,expected_tags",
    [
        ("tags_become_products", {"tags": ["projects", "insights"]}, ["insights"], ["insights", "things"]),
        ("explicit_product_wins", {"tags": ["insights"], "x-product": "error-tracking"}, ["error_tracking"], None),
        ("explicit_product_list", {"tags": [], "x-product": ["core", "logs"]}, ["core", "logs"], None),
        ("swagger_tag_replaces_tags", {"tags": ["insights"], "x-swagger-tag": "Custom"}, ["insights"], ["Custom"]),
    ],
)
def test_postprocess_resolves_product_and_tags(
    _name: str, extra: dict[str, Any], expected_product: list[str], expected_tags: list[str] | None
) -> None:
    preprocess_exclude_path_format([])
    spec = {"paths": {"/api/projects/{project_id}/things/": {"get": {"operationId": "things_list", **extra}}}}

    result = custom_postprocessing_hook(spec, generator=None, request=None, public=True)
    op = result["paths"]["/api/projects/{project_id}/things/"]["get"]

    assert op["x-product"] == expected_product
    if expected_tags is not None:
        assert op["tags"] == expected_tags
        assert {"name": expected_tags[-1]} in result["tags"]


def test_postprocess_normalizes_parameters_components_and_metadata() -> None:
    preprocess_exclude_path_format([])
    spec = {
        "paths": {
            "/api/projects/{project_id}/insights/{id}/": {
                "get": _operation(
                    "insights_retrieve",
                    parameters=[
                        {"in": "path", "name": "project_id", "required": True, "schema": {"type": "string"}},
                        {"in": "path", "name": "id", "required": True, "schema": {"type": ["integer", "null"]}},
                        {"in": "path", "name": "slug", "schema": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
                        {"in": "query", "name": "limit", "schema": {"type": "integer", "nullable": True}},
                    ],
                    requestBody={"content": {"application/json": {"schema": {"allOf": [{"$ref": "#/a"}]}}}},
                    responses={"200": {"content": {"application/json": {"schema": {"allOf": [{"$ref": "#/b"}]}}}}},
                )
            }
        },
        "components": {
            "schemas": {
                "Insight": {
                    "type": "object",
                    "properties": {"dashboards": {}, "dashboard_tiles": {}},
                    "required": ["dashboards", "dashboard_tiles"],
                }
            }
        },
    }

    result = custom_postprocessing_hook(spec, generator=None, request=None, public=True)
    op = result["paths"]["/api/projects/{project_id}/insights/{id}/"]["get"]

    assert op["parameters"] == [
        {"$ref": "#/components/parameters/ProjectIdPath"},
        {"in": "path", "name": "id", "required": True, "schema": {"type": "integer"}},
        {"in": "path", "name": "slug", "schema": {"type": "string"}},
        {"in": "query", "name": "limit", "schema": {"type": ["integer", "null"]}},
    ]
    assert op["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/a"}
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/b"}
    assert result["components"]["schemas"]["Insight"]["required"] == ["dashboard_tiles"]
    assert set(result["components"]["parameters"]) == {"ProjectIdPath", "EnvironmentIdPath", "OrganizationIdPath"}
    assert result["info"] == {"title": "PostHog API", "version": "1.0.0", "description": ""}
    assert result["tags"] == [{"name": "insights"}]
    assert result["x-tagGroups"] == [{"name": "All endpoints", "tags": ["insights"]}]
