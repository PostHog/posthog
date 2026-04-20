from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from posthog.models import Team, User

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class MCPTool(ABC, Generic[ArgsT]):
    """
    Base class for tools executable via MCP callers.

    Unlike MaxTool, this interface:
    - Only takes args (no LangChain state, config, context_manager)
    - Team/user stored as instance fields from API authentication
    - No artifact creation (returns data directly)
    - Raises MaxToolError on failure (matching MaxTool conventions)
    """

    name: str
    args_schema: type[ArgsT]

    def __init__(self, team: Team, user: User):
        self._team = team
        self._user = user

    @abstractmethod
    async def execute(self, args: ArgsT) -> str:
        """
        Execute the tool with validated args.

        Returns:
            Content string for LLM consumption.

        Raises:
            MaxToolRetryableError: For errors that can be fixed with adjusted inputs.
            MaxToolFatalError: For errors that cannot be recovered from.
        """
        pass


@dataclass(frozen=True)
class MCPToolRegistration:
    tool_cls: type[MCPTool[Any]]
    scopes: list[str]


class MCPToolRegistry:
    """Singleton registry for MCP tools."""

    _instance: "MCPToolRegistry | None" = None
    _tools: dict[str, MCPToolRegistration]

    def __new__(cls) -> "MCPToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = {}
        return cls._instance

    def register(self, scopes: list[str] | None = None):
        """Decorator factory to register an MCP tool with optional scopes."""

        def decorator[T: MCPTool[Any]](cls: type[T]) -> type[T]:
            self._tools[cls.name] = MCPToolRegistration(
                tool_cls=cls,
                scopes=scopes or [],
            )
            return cls

        return decorator

    def get(self, name: str, team: Team, user: User) -> MCPTool[Any] | None:
        """Get an MCP tool instance by name, constructed with team/user."""
        import ee.hogai.tools  # noqa: F401 - ensure tools are registered

        registration = self._tools.get(name)
        if registration:
            return registration.tool_cls(team=team, user=user)
        return None

    def get_scopes(self, name: str) -> list[str]:
        """Get the required scopes for a registered MCP tool."""
        import ee.hogai.tools  # noqa: F401 - ensure tools are registered

        registration = self._tools.get(name)
        if registration:
            return registration.scopes
        return []

    def get_names(self) -> list[str]:
        """Get list of registered MCP tool names."""
        return list(self._tools.keys())


mcp_tool_registry = MCPToolRegistry()
