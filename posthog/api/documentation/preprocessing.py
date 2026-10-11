"""Preprocessing hook: filter endpoints, mark env/org duplicates, record product ownership."""

import re
from typing import Any

from posthog.products import is_product_module

from . import autoschema

# Global mapping of (path, method) → product folder, populated during preprocessing
_endpoint_product_mapping: dict[tuple[str, str], str] = {}

# Set of (path, method) for org-level paths that duplicate a /api/projects/ path.
# These get marked deprecated and prefixed with "org_" in postprocessing.
_org_paths_with_project_dup: set[tuple[str, str]] = set()

# Match any /api/{root}/{parent_lookup_*}/ prefix regardless of the lookup variable name.
# This handles registrations that use team_id, project_id, organization_id, etc.
_PROJECTS_PREFIX_RE = re.compile(r"^/api/projects/\{parent_lookup_\w+\}/")

_ENVIRONMENTS_PREFIX_RE = re.compile(r"^/api/environments/\{parent_lookup_\w+\}/")

_ORG_PREFIX_RE = re.compile(r"^/api/organizations/\{parent_lookup_\w+\}/")


def _get_product_from_module(module: str) -> str | None:
    """Extract product folder name from module path like 'products.batch_exports.backend.api'."""
    if is_product_module(module):
        parts = module.split(".")
        if len(parts) >= 2:
            return parts[1]
    return None


def _extract_root_suffix(prefix_re: re.Pattern, path: str) -> str | None:
    """Extract the resource suffix after the root /api/{resource}/{lookup}/ prefix, or None."""
    m = prefix_re.match(path)
    return path[m.end() :] if m else None


def preprocess_exclude_path_format(endpoints, **kwargs):
    """
    preprocessing hook that filters out {format} suffixed paths, in case
    format_suffix_patterns is used and {format} path params are unwanted.

    Also tracks endpoints registered under both /api/environments/ and
    /api/projects/ so that environment duplicates can be marked deprecated in
    postprocessing.  Also detects /api/organizations/ paths that duplicate a
    /api/projects/ path (same resource suffix) for the same treatment.

    Uses regex-based prefix matching so it works regardless of which
    {parent_lookup_*} variable name a registration chose (team_id vs project_id
    vs organization_id, etc.).
    """
    # For frontend type generation, include INTERNAL views if they have explicit tags
    include_internal = autoschema._include_internal_operations()

    # Clear previous mappings
    _endpoint_product_mapping.clear()
    _org_paths_with_project_dup.clear()

    # Pass 1: collect all included endpoints and build a set of suffixes that
    # exist under /api/projects/ so we can identify /api/environments/ and
    # /api/organizations/ duplicates.
    included: list[tuple[str, str, str, Any]] = []
    projects_suffixes: set[tuple[str, str]] = set()

    for path, path_regex, method, callback in endpoints:
        force_include = getattr(callback.cls, "force_include_in_api_docs", False)

        if getattr(callback.cls, "param_derived_from_user_current_team", None) and not force_include:
            # Root-router viewsets don't fit the /api/projects/{team_id}/... pattern; opt in via
            # `force_include_in_api_docs = True` to surface in type-gen and MCP scaffolding.
            continue
        has_scope_object = hasattr(callback.cls, "scope_object")
        # A view with no scope_object is normally excluded - the schema is built around
        # team/org-scoped resources. include_in_api_docs is the explicit opt-in for a
        # deliberately unscoped view (e.g. a public, unauthenticated endpoint) that still
        # wants to appear in the docs.
        if not has_scope_object and not getattr(callback.cls, "include_in_api_docs", False):
            continue
        if getattr(callback.cls, "hide_api_docs", False):
            continue
        if has_scope_object:
            scope = callback.cls.scope_object
            if scope == "INTERNAL" and not include_internal:
                continue

        included.append((path, path_regex, method, callback))
        suffix = _extract_root_suffix(_PROJECTS_PREFIX_RE, path)
        if suffix is not None:
            projects_suffixes.add((suffix, method))

    # Pass 2: keep all endpoints, but mark env/org duplicates for deprecation in postprocessing.
    # Env duplicates get {environment_id} param (matching _DEPRECATED_ENV_PREFIX).
    # Org duplicates are tracked in _org_paths_with_project_dup by their final path string.
    # All other {parent_lookup_*} variables are collapsed to the simple name.
    # drf-spectacular may rewrite other params (e.g. {pk} → {id}) between pre- and postprocessing,
    # so postprocessing identifies deprecated paths by prefix/set membership, not exact match.
    result = []
    for path, path_regex, method, callback in included:
        env_suffix = _extract_root_suffix(_ENVIRONMENTS_PREFIX_RE, path)
        is_env_duplicate = env_suffix is not None and (env_suffix, method) in projects_suffixes

        org_suffix = _extract_root_suffix(_ORG_PREFIX_RE, path)
        is_org_duplicate = org_suffix is not None and (org_suffix, method) in projects_suffixes

        if is_env_duplicate:
            path = _ENVIRONMENTS_PREFIX_RE.sub("/api/environments/{environment_id}/", path, count=1)
        elif _ENVIRONMENTS_PREFIX_RE.match(path):
            path = _ENVIRONMENTS_PREFIX_RE.sub("/api/environments/{project_id}/", path, count=1)
        else:
            # For projects/org paths, {parent_lookup_team_id} → {project_id} (legacy convention).
            path = path.replace("{parent_lookup_team_id}", "{project_id}")
        # Collapse any remaining {parent_lookup_X} → {X}
        path = path.replace("{parent_lookup_", "{")

        if is_org_duplicate:
            # Normalize {pk} → {id} to match what drf-spectacular emits in postprocessing.
            _org_paths_with_project_dup.add((path.replace("{pk}", "{id}"), method))

        # Track product folder for auto-tagging
        product = _get_product_from_module(callback.cls.__module__)
        if product:
            # Normalize {pk} → {id} so postprocessing lookup matches drf-spectacular's emission.
            _endpoint_product_mapping[(path.replace("{pk}", "{id}"), method)] = product

        result.append((path, path_regex, method, callback))
    return result
