"""Read the committed MCP tool catalogue.

`services/mcp/schema/` holds the tool definitions the MCP server advertises: the
hand-written tools in `tool-definitions.json` and the code-generated ones in
`generated-tool-definitions.json`. Both files ship in this repository, so any Django
process can answer what tools exist without a runtime call to the resource server.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from posthog.dataclasses import frozen
from posthog.settings.base_variables import BASE_DIR

_SCHEMA_DIR = Path(BASE_DIR) / "services" / "mcp" / "schema"

# Hand-written first, generated second, so the generated definition wins on the seven names
# both files hold. This is the precedence `getToolDefinitions()` in
# services/mcp/src/tools/toolDefinitions.ts merges with, and a catalogue built the other way
# round would describe a tool the server does not serve. Both files are needed: some tools
# exist only as hand-written ones (for example read-data-schema), and they are the only users
# of some scopes.
_TOOL_DEFINITION_PATHS = (
    _SCHEMA_DIR / "tool-definitions.json",
    _SCHEMA_DIR / "generated-tool-definitions.json",
)

FeatureFlagBehavior = Literal["enable", "disable"]


@frozen
class McpToolDefinition:
    """One entry of the MCP tool catalogue.

    The fields mirror `ToolDefinitionSchema` in services/mcp/src/tools/toolDefinitions.ts.
    `description` runs to several kilobytes on the query tools, so a caller that lists the
    whole catalogue reads `summary` instead.
    """

    name: str
    title: str
    summary: str
    description: str
    category: str
    feature: str
    required_scopes: tuple[str, ...]
    read_only: bool
    requires_ai_consent: bool
    # The flag gate, exactly as services/mcp/src/tools/toolDefinitions.ts reads it. The gate
    # resolves per project, so a caller that needs the served catalogue for one project
    # evaluates these itself.
    feature_flag: str | None
    feature_flag_behavior: FeatureFlagBehavior | None
    feature_flag_variant: str | None
    hidden_when_flag_on: str | None
    # Names that took over this tool's job. A superseded tool is on its way out, so a surface
    # that offers a choice of tools offers its successors instead.
    superseded_by: tuple[str, ...]
    feature_entitlement: str | None

    @property
    def is_superseded(self) -> bool:
        return bool(self.superseded_by)


def _definition_from_json(name: str, raw: Mapping[str, Any]) -> McpToolDefinition:
    return McpToolDefinition(
        name=name,
        title=raw["title"],
        summary=raw["summary"],
        description=raw["description"],
        category=raw["category"],
        feature=raw["feature"],
        required_scopes=tuple(raw.get("required_scopes") or ()),
        read_only=bool(raw["annotations"]["readOnlyHint"]),
        requires_ai_consent=bool(raw.get("requires_ai_consent", False)),
        feature_flag=raw.get("feature_flag"),
        feature_flag_behavior=raw.get("feature_flag_behavior"),
        feature_flag_variant=raw.get("feature_flag_variant"),
        hidden_when_flag_on=raw.get("hidden_when_flag_on"),
        superseded_by=tuple(raw.get("superseded_by") or ()),
        feature_entitlement=raw.get("feature_entitlement"),
    )


@lru_cache(maxsize=1)
def get_mcp_tool_definitions() -> Mapping[str, McpToolDefinition]:
    """Every catalogued MCP tool, keyed by tool name.

    The files are committed artifacts, so the result is read once per process.
    """
    merged: dict[str, Any] = {}
    for path in _TOOL_DEFINITION_PATHS:
        merged.update(json.loads(path.read_text()))

    return MappingProxyType({name: _definition_from_json(name, raw) for name, raw in merged.items()})


@lru_cache(maxsize=1)
def mcp_tool_required_scopes() -> frozenset[str]:
    """Every scope some catalogued tool requires."""
    return frozenset(
        scope for definition in get_mcp_tool_definitions().values() for scope in definition.required_scopes
    )
