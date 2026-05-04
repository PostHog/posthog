"""
Shared OpenAPI parameter factories for endpoints that accept the
`variables_override` / `filters_override` query params.

Three semantics are easy to miss without reading posthog/utils.py and
posthog/api/insight_variable.py, so they're documented once here:

  1. Each variable entry needs `code_name` to match — `map_stale_to_latest`
     drops entries that lack it, so an override of `{"value": ...}` alone
     silently no-ops.
  2. Both helpers shallow-merge — top-level keys replace wholesale, nested
     values are not deep-merged.
  3. Both helpers ignore overrides when the request is authenticated via a
     sharing token, returning the persisted state with no error.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

# OpenAPI extension marking a query parameter whose wire format is a stringified
# JSON object. Consumers (currently the MCP codegen at
# services/mcp/scripts/generate-tools.ts) widen the input schema to accept either
# a pre-encoded JSON string or a plain object; the runtime then JSON.stringify-s
# objects before placing them on the URL. The extension is intentionally generic
# rather than MCP-scoped — frontend codegen and any other downstream consumer
# can read the same fact about the param.
ACCEPTS_STRINGIFIED_JSON = {"x-accepts-stringified-json": True}


def make_variables_override_param(*, subject_label: str, tool_name: str) -> OpenApiParameter:
    """OpenAPI definition for `variables_override`.

    Args:
        subject_label: e.g. "dashboard" or "the insight's HogQL" — appears as
            "<subject_label> variables" in the description.
        tool_name: MCP tool to reference in the workflow hint, e.g.
            "dashboard-get" or "insight-get".
    """
    return OpenApiParameter(
        "variables_override",
        OpenApiTypes.STR,
        description=(
            f"Object (or pre-encoded JSON string) to override {subject_label} variables for this request only (not persisted). "
            'Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. '
            "Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is "
            f"to call `{tool_name}` first, copy the matching entry from the response, and mutate `value`. "
            "Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token."
        ),
        extensions=ACCEPTS_STRINGIFIED_JSON,
    )


def make_filters_override_param(*, subject_label: str) -> OpenApiParameter:
    """OpenAPI definition for `filters_override`.

    Args:
        subject_label: e.g. "dashboard" or "the insight's" — appears as
            "<subject_label> filters" in the description.
    """
    return OpenApiParameter(
        "filters_override",
        OpenApiTypes.STR,
        description=(
            f"Object (or pre-encoded JSON string) to override {subject_label} filters for this request only (not persisted). "
            "Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. "
            "Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). "
            "Ignored when accessed via a sharing token."
        ),
        extensions=ACCEPTS_STRINGIFIED_JSON,
    )
