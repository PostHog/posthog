from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from posthog.models import Team, User


class ExternalToolResult(BaseModel):
    """Result from external tool execution."""

    success: bool
    content: str  # Text for LLM consumption
    data: dict[str, Any] | None = None  # Structured data (query results, etc.)
    error: str | None = None


class ExternalTool(ABC):
    """
    Base class for tools executable via external callers (MCP, API).

    Unlike MaxTool, this interface:
    - Only takes args (no LangChain state, config, context_manager)
    - Team/user derived from API authentication
    - No artifact creation (returns data directly)
    """

    name: str
    args_schema: type[BaseModel]

    @abstractmethod
    async def execute(self, team: "Team", user: "User", **args) -> ExternalToolResult:
        """Execute the tool with minimal context."""
        pass


# Registry for external tools
EXTERNAL_TOOL_REGISTRY: dict[str, type[ExternalTool]] = {}


def register_external_tool(cls: type[ExternalTool]) -> type[ExternalTool]:
    """Decorator to register an external tool."""
    EXTERNAL_TOOL_REGISTRY[cls.name] = cls
    return cls


def get_external_tool(name: str) -> ExternalTool | None:
    """Get an external tool instance by name."""
    tool_cls = EXTERNAL_TOOL_REGISTRY.get(name)
    if tool_cls:
        return tool_cls()
    return None


def get_external_tool_names() -> list[str]:
    """Get list of registered external tool names."""
    return list(EXTERNAL_TOOL_REGISTRY.keys())
