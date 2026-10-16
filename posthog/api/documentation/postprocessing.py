"""Postprocessing hook: product routing, tags, operation IDs and shared path parameters."""

import re
from typing import Any

from . import preprocessing, schema_normalization

# Canonical parameter component definitions for the highest-frequency path params. drf-spectacular
# inlines these into every operation that uses them — ``project_id`` alone shows up ~1100 times in
# the spec, with byte-identical schema and description each time. Hoisting them into
# ``components.parameters`` and ``$ref``-ing them eliminates the repetition (smaller spec, single
# source of truth, kills vacuum's ``description-duplication`` for these names) without changing
# what downstream codegen produces.
_SHARED_PATH_PARAMS: dict[str, dict[str, Any]] = {
    "ProjectIdPath": {
        "in": "path",
        "name": "project_id",
        "required": True,
        "schema": {"type": "string"},
        "description": "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/.",
    },
    "EnvironmentIdPath": {
        "in": "path",
        "name": "environment_id",
        "required": True,
        "schema": {"type": "string"},
        "description": "Deprecated. Use /api/projects/{project_id}/ instead.",
    },
    "OrganizationIdPath": {
        "in": "path",
        "name": "organization_id",
        "required": True,
        "schema": {"type": "string"},
        "description": "ID of the organization you're trying to access. To find the ID of the organization, make a call to /api/organizations/.",
    },
}

# Reverse lookup keyed by the inlined parameter name.
_SHARED_PATH_PARAM_REFS: dict[str, str] = {p["name"]: name for name, p in _SHARED_PATH_PARAMS.items()}

# Prefix used to identify deprecated environment duplicates in postprocessing.
# Only env paths that duplicate a /api/projects/ path get this prefix (via {environment_id}).
_DEPRECATED_ENV_PREFIX = "/api/environments/{environment_id}/"

# Match finalized paths (after {parent_lookup_*} substitution) for postprocessing.
_ORG_PROJECTS_FINAL_RE = re.compile(r"^/api/organizations/[^/]+/projects/")


def custom_postprocessing_hook(result, generator, request, public):
    all_tags = []
    paths: dict[str, dict] = {}

    for path, methods in result["paths"].items():
        paths[path] = {}
        is_deprecated_env = path.startswith(_DEPRECATED_ENV_PREFIX)

        for method, definition in methods.items():
            if is_deprecated_env:
                definition["deprecated"] = True

            # Resolve x-product for codegen routing.
            #
            # Priority (highest first):
            #   1. Explicit ``@extend_schema(extensions={"x-product": ...})`` — authoritative.
            #      Accepts a string, enum-like (e.g. ``ProductKey.X``, stringified), or a list.
            #      Kebab values are normalized to snake_case so output matches folder names.
            #      When present, NOTHING else is added — the dev intent wins. Use this to send
            #      an endpoint to the core bucket from inside ``products/<X>/backend/`` (e.g.
            #      ``extensions={"x-product": "core"}``).
            #   2. ``@extend_schema(tags=[...])`` values — supported for legacy call sites; the
            #      explicit form above is preferred for new code. Non-folder values pass through
            #      here; consumers ignore anything that doesn't match a product folder or
            #      definition file (tags=[...] is for display, not routing).
            #   3. Module-path auto-attribution: ViewSet in ``products/<name>/backend/`` → ``<name>``.
            #
            # The resulting list is read by ``generate-openapi-types.mjs`` and
            # ``services/mcp/scripts/scaffold-yaml.ts``.
            x_product_override = definition.pop("x-product", None)
            if x_product_override is not None and not isinstance(x_product_override, list):
                x_product_override = [x_product_override]

            if x_product_override:
                x_product = [str(v).replace("-", "_") for v in x_product_override]
            else:
                x_product = [d for d in definition.get("tags", []) if d not in ["projects", "environments"]]
                module_product = preprocessing._endpoint_product_mapping.get((path, method.upper()))
                if module_product and module_product not in x_product:
                    x_product.append(module_product)

            definition["x-product"] = x_product

            definition["tags"] = [d for d in definition["tags"] if d not in ["projects", "environments"]]

            # If a ViewSet sets x-swagger-tag via @extend_schema(extensions={"x-swagger-tag": "..."}),
            # use that as the sole display tag instead of appending the URL-derived one.
            # This controls Swagger UI grouping without affecting x-product (used for codegen).
            swagger_tag = definition.pop("x-swagger-tag", None)
            if swagger_tag:
                definition["tags"] = [swagger_tag]
            else:
                match = re.search(
                    r"((\/api\/(organizations|projects|environments)/{(.*?)}\/)|(\/api\/))(?P<one>[a-zA-Z0-9-_]*)\/",
                    path,
                )
                if match:
                    definition["tags"].append(match.group("one"))
            for tag in definition["tags"]:
                all_tags.append(tag)

            # Strip router-derived prefixes from operationIds.
            #
            # Rules:
            # - Deprecated env paths keep their environments_ prefix (distinguishes them from the
            #   canonical project version that Orval will use).
            # - Org paths that duplicate a project path get an org_ prefix and are marked deprecated.
            # - /api/organizations/{id}/projects/… paths must NOT have projects_ stripped — that
            #   segment is the resource name, not a router namespace, and stripping it collapses
            #   everything to e.g. "list"/"create" which then collides with top-level org paths.
            # - Everything else: strip projects_/environments_ (router-namespace noise).
            is_org_dup = (path, method.upper()) in preprocessing._org_paths_with_project_dup
            is_org_projects = bool(_ORG_PROJECTS_FINAL_RE.match(path))

            if is_org_dup:
                definition["deprecated"] = True
                op_id = definition["operationId"]
                if not op_id.startswith("org_"):
                    definition["operationId"] = "org_" + op_id
            elif not is_org_projects:
                # Only strip organizations_ for non-org/projects paths (it's a root-level prefix)
                definition["operationId"] = definition["operationId"].replace("organizations_", "", 1)

            if is_deprecated_env:
                # Ensure the operationId carries the environments_ namespace even when an
                # explicit @extend_schema(operation_id=...) was used on the ViewSet method.
                op_id = definition["operationId"]
                if not op_id.startswith("environments_"):
                    definition["operationId"] = "environments_" + op_id
            elif not is_org_dup:
                op_id = definition["operationId"]
                if not is_org_projects:
                    op_id = op_id.replace("projects_", "", 1)
                op_id = op_id.replace("environments_", "", 1)
                definition["operationId"] = op_id

            if "parameters" in definition:
                definition["parameters"] = [
                    {"$ref": f"#/components/parameters/{_SHARED_PATH_PARAM_REFS[param['name']]}"}
                    if param.get("name") in _SHARED_PATH_PARAM_REFS and param.get("in") == "path"
                    else schema_normalization._strip_null_from_path_param(param)
                    if param.get("in") == "path"
                    else param
                    for param in definition["parameters"]
                ]
            paths[path][method] = definition

    # Apply OpenAPI 3.1 schema cleanup to all component schemas.
    if "components" in result and "schemas" in result["components"]:
        result["components"]["schemas"] = {
            name: schema_normalization._unrequire_deprecated_dashboards_field(
                schema_normalization._fix_pydantic_schema_for_openapi(schema)
            )
            for name, schema in result["components"]["schemas"].items()
        }

    # Apply the same cleanup to parameter, requestBody, and response schemas at the operation
    # level — single-entry allOf wrappers and vestigial bounds also surface there.  Today
    # every response schema we emit is a ``$ref`` to a component, so the response walk is a
    # defensive guarantee — if someone adds an inline response schema later it gets cleaned
    # up proactively instead of failing the consistency lint downstream.
    def _fix_media_types(content: Any) -> None:
        if not isinstance(content, dict):
            return
        for media_type in content.values():
            if isinstance(media_type, dict) and isinstance(media_type.get("schema"), dict):
                media_type["schema"] = schema_normalization._fix_pydantic_schema_for_openapi(media_type["schema"])

    for path_methods in paths.values():
        for definition in path_methods.values():
            for parameter in definition.get("parameters", []):
                if isinstance(parameter, dict) and isinstance(parameter.get("schema"), dict):
                    parameter["schema"] = schema_normalization._fix_pydantic_schema_for_openapi(parameter["schema"])
            request_body = definition.get("requestBody")
            if isinstance(request_body, dict):
                _fix_media_types(request_body.get("content"))
            for response in (definition.get("responses") or {}).values():
                if isinstance(response, dict):
                    _fix_media_types(response.get("content"))

    # Emit a root-level ``tags`` array listing every tag any operation references. Vacuum's
    # ``operation-tag-defined`` rule requires this — operations that use undeclared tags
    # produce a finding per (operation, tag) pair (was 2962 findings for us).
    sorted_tags = sorted(set(all_tags))

    # Hoist shared path parameter definitions into ``components.parameters`` so the per-operation
    # ``$ref``s emitted earlier resolve correctly.
    components = dict(result.get("components") or {})
    components["parameters"] = {**(components.get("parameters") or {}), **_SHARED_PATH_PARAMS}

    return {
        **result,
        "info": {"title": "PostHog API", "version": "1.0.0", "description": ""},
        "paths": paths,
        "components": components,
        "tags": [{"name": tag} for tag in sorted_tags],
        "x-tagGroups": [{"name": "All endpoints", "tags": sorted_tags}],
    }
