from __future__ import annotations

from typing import Any

from ee.hogai.ai.product_registry import get_all_tool_schemas
from ee.hogai.tool import get_contextual_tool_class


def build_available_tools(team, user, contextual_names: set[str]) -> list[Any]:
    """
    Assemble tools with explicit precedence.

    Precedence by insertion order:
    1) Core + Product schemas (skip when name is contextual)
    2) Contextual instances (overwrite any previous entry)

    First-party legacy tools (e.g., create_dashboard) are handled by callers
    until migrated into MaxTools and then inside AIProducts.
    """
    tools_by_name: dict[str, Any] = {}

    # Core + Product schemas
    for Schema in get_all_tool_schemas(team, user):
        name = getattr(Schema, "__name__", None)
        if not name:
            continue
        if name in contextual_names:
            continue
        # Insert only if absent to preserve first-in precedence
        if name not in tools_by_name:
            tools_by_name[name] = Schema

    # Contextual instances (overwrite to take precedence)
    for name in contextual_names:
        ToolClass = get_contextual_tool_class(name)
        if ToolClass:
            tools_by_name[name] = ToolClass(team=team, user=user)

    return list(tools_by_name.values())
