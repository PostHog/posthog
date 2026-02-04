from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from posthog.models import Team, User

ArgsT = TypeVar("ArgsT", bound=BaseModel)


class ExternalTool(ABC, Generic[ArgsT]):
    """
    Base class for tools executable via external callers (MCP, API).

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
    async def execute(self, args: ArgsT) -> tuple[str, dict[str, Any] | None]:
        """
        Execute the tool with validated args.

        Returns:
            Tuple of (content_str, optional_data_dict).

        Raises:
            MaxToolRetryableError: For errors that can be fixed with adjusted inputs.
            MaxToolFatalError: For errors that cannot be recovered from.
        """
        pass


@dataclass(frozen=True)
class ExternalToolRegistration:
    tool_cls: type[ExternalTool[Any]]
    scopes: list[str]


# Registry for external tools
EXTERNAL_TOOL_REGISTRY: dict[str, ExternalToolRegistration] = {}


def register_external_tool(scopes: list[str] | None = None):
    """Decorator factory to register an external tool with optional scopes."""

    def decorator[T: ExternalTool[Any]](cls: type[T]) -> type[T]:
        EXTERNAL_TOOL_REGISTRY[cls.name] = ExternalToolRegistration(
            tool_cls=cls,
            scopes=scopes or [],
        )
        return cls

    return decorator


def get_external_tool(name: str, team: Team, user: User) -> ExternalTool[Any] | None:
    """Get an external tool instance by name, constructed with team/user."""
    registration = EXTERNAL_TOOL_REGISTRY.get(name)
    if registration:
        return registration.tool_cls(team=team, user=user)
    return None


def get_external_tool_scopes(name: str) -> list[str]:
    """Get the required scopes for a registered external tool."""
    registration = EXTERNAL_TOOL_REGISTRY.get(name)
    if registration:
        return registration.scopes
    return []


def get_external_tool_names() -> list[str]:
    """Get list of registered external tool names."""
    return list(EXTERNAL_TOOL_REGISTRY.keys())
