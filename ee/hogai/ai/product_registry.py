import pkgutil
import importlib

from ee.hogai.ai import products as builtin_products
from ee.hogai.ai.core_tools import get_core_tool_schemas
from ee.hogai.ai.product_base import AI_PRODUCT_REGISTRY
from ee.hogai.tool import MaxTool, get_contextual_tool_class

GLOBAL_TOOL_NAME_TO_TOOL: dict[str, type[MaxTool]] = {}
_PRODUCTS_IMPORTED = False


def _import_ai_products() -> None:
    global _PRODUCTS_IMPORTED
    if _PRODUCTS_IMPORTED:
        return
    # Built-in AI products in ee/hogai/ai/products/*
    for module_info in pkgutil.iter_modules(builtin_products.__path__):
        importlib.import_module(f"{builtin_products.__name__}.{module_info.name}")

    _PRODUCTS_IMPORTED = True


def _index_global_tools() -> None:
    GLOBAL_TOOL_NAME_TO_TOOL.clear()
    for Product in AI_PRODUCT_REGISTRY.values():
        for Tool in getattr(Product, "tools", []) or []:
            # Resolve tool name in a way compatible with Pydantic v2 BaseModel class attribute handling
            tool_name = getattr(Tool, "name", None)
            if tool_name is None:
                model_fields = getattr(Tool, "model_fields", None)
                if model_fields and "name" in model_fields and getattr(model_fields["name"], "default", None):
                    tool_name = model_fields["name"].default
                else:
                    tool_name = Tool.__name__
            GLOBAL_TOOL_NAME_TO_TOOL[str(tool_name)] = Tool


def ensure_products_loaded() -> None:
    _import_ai_products()
    _index_global_tools()


def get_all_tool_schemas(team, user):
    """
    Return core tool schemas + product tool schemas.
    """
    ensure_products_loaded()
    core = get_core_tool_schemas(team, user)
    product = []
    for Product in AI_PRODUCT_REGISTRY.values():
        if Product.is_available(team, user):
            product.extend(Product.tool_schemas())
    total = [*core, *product]
    return total


def get_tool_class(tool_name: str) -> type[MaxTool] | None:
    ensure_products_loaded()
    if tool_name in GLOBAL_TOOL_NAME_TO_TOOL:
        t = GLOBAL_TOOL_NAME_TO_TOOL[tool_name]
        return t
    try:
        return get_contextual_tool_class(tool_name)
    except Exception:
        return None
