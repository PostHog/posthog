import pkgutil
import importlib
from typing import TYPE_CHECKING

from posthog.schema import AssistantTool

import products

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool

CONTEXTUAL_TOOL_NAME_TO_TOOL: dict[AssistantTool, type["MaxTool"]] = {}


def _import_max_tools() -> None:
    """TRICKY: Dynamically import max_tools from all products"""
    # Already imported
    if CONTEXTUAL_TOOL_NAME_TO_TOOL:
        return

    for module_info in pkgutil.iter_modules(products.__path__):
        if module_info.name in ("conftest", "test"):
            continue  # We mustn't import test modules in prod
        try:
            importlib.import_module(f"products.{module_info.name}.backend.max_tools")
        except ModuleNotFoundError:
            pass  # Skip if backend or max_tools doesn't exist - note that the product's dir needs a top-level __init__.py


def get_contextual_tool_class(tool_name: str) -> type["MaxTool"] | None:
    """Get the tool class for a given tool name, handling circular import."""
    _import_max_tools()  # Ensure max_tools are imported
    from ee.hogai.tool import CONTEXTUAL_TOOL_NAME_TO_TOOL

    try:
        return CONTEXTUAL_TOOL_NAME_TO_TOOL[AssistantTool(tool_name)]
    except KeyError:
        return None
