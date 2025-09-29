"""
Core infrastructure for AIProducts and tools.
- AIProduct: Base class for grouping related MaxTools
- AIRegistry: Global registration of products and tools
- Schema generation: Dynamic Pydantic model creation for tool schemas
- Tool discovery: Runtime loading and assembly of available tools

* Products are auto-discovered from ee/hogai/ai/products/*
* Each product registers itself and its tools
* Tools are assembled with precedence: core → product → contextual
"""

from __future__ import annotations

import pkgutil
import importlib
from collections.abc import Sequence
from typing import Any

from django.conf import settings

from pydantic import BaseModel

from posthog.models import Team
from posthog.models.user import User

from ee.hogai.tool import MaxTool, get_contextual_tool_class, search_documentation


class AIRegistry:
    """Centralized registry for AI products and MaxTools."""

    products: dict[str, type[AIProduct]] = {}
    tools: dict[str, type[MaxTool]] = {}
    schema_cache: dict[type[MaxTool], type[BaseModel]] = {}
    _initialized: bool = False

    @classmethod
    def reset(cls) -> None:
        """Important for testing"""
        cls.products.clear()
        cls.tools.clear()
        cls.schema_cache.clear()
        cls._initialized = False


registry = AIRegistry()


def tool_to_schema(Tool: type[MaxTool]) -> type[BaseModel]:
    """Convert MaxTool to Pydantic schema for function binding."""
    if cached := registry.schema_cache.get(Tool):
        return cached

    # Get tool name (check model_fields for Pydantic, then fallback to attribute)
    tool_name = Tool.__name__
    if hasattr(Tool, "model_fields") and "name" in Tool.model_fields:
        if name := Tool.model_fields["name"].default:
            tool_name = name
    elif hasattr(Tool, "name"):
        tool_name = Tool.name

    # Get args schema
    schema_cls = None
    if hasattr(Tool, "model_fields") and "args_schema" in Tool.model_fields:
        schema_cls = Tool.model_fields["args_schema"].default
    if not schema_cls:
        schema_cls = Tool.__dict__.get("args_schema") or getattr(Tool, "args_schema", None)
    if not schema_cls:
        schema_cls = type(f"{tool_name}_Args", (BaseModel,), {})

    # Create schema with correct name and description
    PydanticTool = type(tool_name, (schema_cls,), {})  # type: ignore[arg-type]
    desc = ""
    if hasattr(Tool, "model_fields") and "description" in Tool.model_fields:
        desc = Tool.model_fields["description"].default or ""
    elif hasattr(Tool, "description"):
        desc = Tool.description or ""
    PydanticTool.__doc__ = desc

    registry.schema_cache[Tool] = PydanticTool
    return PydanticTool


class AIProduct:
    """Base class for grouping MaxTools under an AI Product identity."""

    name: str

    # Routing hint
    routing_prompt: str

    # Injected when enabled
    system_prompt: str

    # Set of MaxTools belonging to this product
    tools: Sequence[type[MaxTool]]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Validate required attributes
        for attr in ["name", "routing_prompt", "system_prompt", "tools"]:
            if not hasattr(cls, attr):
                raise ValueError(f"AIProduct subclass {cls.__name__} must define {attr}")
        if not cls.name:
            raise ValueError(f"AIProduct subclass {cls.__name__} must have a non-empty name")
        registry.products[cls.name] = cls

    @classmethod
    def is_available(cls, team: Team, user: User) -> bool:
        """
        Whether the product should be exposed to the current team/user.
        Feature flags and user permissions can be checked here.
        """
        return True

    @classmethod
    def tool_schemas(cls) -> list[type[BaseModel]]:
        """Pydantic schemas for all tools in this product."""
        return [tool_to_schema(Tool) for Tool in cls.tools]


def ensure_products_loaded() -> None:
    """Ensure all products are imported and tools are indexed."""
    if registry._initialized:
        return

    # Import all AI product modules to trigger registration
    from ee.hogai.ai import products as builtin_products

    for module_info in pkgutil.iter_modules(builtin_products.__path__):
        module_name = f"{builtin_products.__name__}.{module_info.name}"
        importlib.import_module(module_name)

    # Index all tools from registered products
    registry.tools.clear()
    for Product in registry.products.values():
        for Tool in Product.tools:
            # Get tool name
            tool_name = Tool.__name__
            if hasattr(Tool, "model_fields") and "name" in Tool.model_fields:
                if name := Tool.model_fields["name"].default:
                    tool_name = name
            elif hasattr(Tool, "name"):
                tool_name = Tool.name
            registry.tools[tool_name] = Tool

    registry._initialized = True


def get_core_tool_schemas(team: Team, user: User) -> list[type[BaseModel]]:
    """Return schemas for core tools that should always be available to the agent."""
    return [search_documentation] if settings.INKEEP_API_KEY else []


def get_all_tool_schemas(team: Team, user: User) -> list[type[BaseModel]]:
    """Return core tool schemas + product tool schemas."""
    ensure_products_loaded()
    schemas = get_core_tool_schemas(team, user)

    for Product in registry.products.values():
        if Product.is_available(team, user):
            schemas.extend(Product.tool_schemas())

    return schemas


def get_tool_class(tool_name: str) -> type[MaxTool] | None:
    """Get tool class by name from registry or contextual tools."""
    ensure_products_loaded()
    if tool_class := registry.tools.get(tool_name):
        return tool_class
    try:
        return get_contextual_tool_class(tool_name)
    except (ImportError, AttributeError, KeyError):
        return None


def build_available_tools(team: Team, user: User, contextual_names: set[str]) -> list[Any]:
    """
    Assemble tools with explicit precedence:
    1) Core + Product schemas (skip when name is contextual)
    2) Contextual instances (overwrite any previous entry)
    """
    tools_by_name: dict[str, Any] = {}

    # Add core and product schemas
    for Schema in get_all_tool_schemas(team, user):
        if (name := getattr(Schema, "__name__", None)) and name not in contextual_names:
            if name not in tools_by_name:  # Preserve first-in precedence
                tools_by_name[name] = Schema

    # Add contextual instances (overwrite to take precedence)
    for name in contextual_names:
        if ToolClass := get_contextual_tool_class(name):
            tools_by_name[name] = ToolClass(team=team, user=user)

    return list(tools_by_name.values())
