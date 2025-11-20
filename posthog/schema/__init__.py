# mypy: disable-error-code="assignment"
"""
Schema module - split into submodules for faster imports.

This module provides backward compatibility. For faster imports, use:
    from posthog.schema.enums import HogQLQueryModifiers
    from posthog.schema.queries import HogQLQuery
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type checkers see everything immediately
    from posthog.schema.core import *  # noqa: F403, F401
    from posthog.schema.enums import *  # noqa: F403, F401
    from posthog.schema.filters import *  # noqa: F403, F401
    from posthog.schema.nodes import *  # noqa: F403, F401
    from posthog.schema.other import *  # noqa: F403, F401
    from posthog.schema.queries import *  # noqa: F403, F401
    from posthog.schema.type_props import *  # noqa: F403, F401
else:
    # Runtime: lazy imports for faster startup
    import importlib
    from types import ModuleType

    _lazy_modules: dict[str, ModuleType] = {}

    def _get_module(name: str) -> ModuleType:
        """Lazily import a submodule using importlib to avoid recursion."""
        if name not in _lazy_modules:
            # Use importlib to import submodules directly, bypassing __init__.py
            module = importlib.import_module(f"posthog.schema.{name}")
            _lazy_modules[name] = module
        return _lazy_modules[name]

    def __getattr__(name: str):
        """Lazy import classes from appropriate submodule."""
        # Try each module in dependency order
        for module_name in ["enums", "type_props", "filters", "nodes", "queries", "core", "other"]:
            try:
                module = _get_module(module_name)
                if hasattr(module, name):
                    return getattr(module, name)
            except (ImportError, AttributeError):
                continue
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
