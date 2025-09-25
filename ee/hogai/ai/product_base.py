from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from posthog.models import Team
from posthog.models.user import User

from ee.hogai.tool import MaxTool

AI_PRODUCT_REGISTRY: dict[str, type[AIProduct]] = {}
_TOOL_SCHEMA_CACHE: dict[type[MaxTool], type[BaseModel]] = {}


def _field_default(cls: type[MaxTool], field: str, fallback: str | None = None) -> str | None:
    """
    Read a Pydantic v2 class field default, prefer model_fields[field].default
    when available, fallback to getattr.
    """
    model_fields = getattr(cls, "model_fields", None)
    if model_fields and field in model_fields:
        default = getattr(model_fields[field], "default", None)
        if default is not None:
            return default  # type: ignore[no-any-return]
    try:
        return getattr(cls, field)  # type: ignore[no-any-return]
    except Exception:
        return fallback


def tool_to_schema(Tool: type[MaxTool]) -> type[BaseModel]:
    """Return a Pydantic model class to bind as a function tool for this MaxTool class.
    The returned class name MUST match the intended tool call name, so we create a dynamic
    model with the tool's `name` while copying the fields of `args_schema` (or an empty model).
    Results are cached per MaxTool class.
    """
    cached = _TOOL_SCHEMA_CACHE.get(Tool)
    if cached is not None:
        return cached

    tool_name = _field_default(Tool, "name", Tool.__name__) or Tool.__name__

    model_fields = getattr(Tool, "model_fields", None)
    schema_cls = None
    if model_fields and "args_schema" in model_fields:
        schema_cls = getattr(model_fields["args_schema"], "default", None)
    if schema_cls is None:
        schema_cls = Tool.__dict__.get("args_schema") or getattr(Tool, "args_schema", None)
    if schema_cls is None:
        schema_cls = type(f"{tool_name}_Args", (BaseModel,), {})

    PydanticTool = type(tool_name, (schema_cls,), {})  # type: ignore[arg-type]
    PydanticTool.__doc__ = _field_default(Tool, "description", "") or ""
    _TOOL_SCHEMA_CACHE[Tool] = PydanticTool
    return PydanticTool


class AIProduct:
    """Base class for grouping MaxTools under an AI Product identity."""

    # Unique identity
    name: str

    # Routing hint
    routing_prompt: str

    # Injected when enabled
    system_prompt: str

    # Set of MaxTools belonging to this product
    tools: Sequence[type[MaxTool]]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "name", None):
            raise ValueError("AIProduct subclasses must set `name`")
        AI_PRODUCT_REGISTRY[cls.name] = cls

    @classmethod
    def is_available(cls, team: Team, user: User) -> bool:
        """
        Whether the product should be exposed to the current team/user.
        Feature flags and user permissions can be checked here.
        """
        return True

    @classmethod
    def tool_schemas(
        cls,
    ) -> list[type[BaseModel]]:
        return [tool_to_schema(Tool) for Tool in cls.tools]
