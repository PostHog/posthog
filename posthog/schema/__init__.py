# mypy: disable-error-code="assignment"
"""
Lazy-loading proxy for schema module.

This module defers importing the actual schema classes until they're first accessed,
reducing startup time from ~3 seconds to near-zero for code paths that don't use schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # For type checkers, import everything directly
    from posthog.schema._generated import *  # noqa: F403, F401
else:
    # Runtime: lazy proxy implementation
    from types import ModuleType

    _module: ModuleType | None = None

    def _get_module() -> ModuleType:
        """Lazily import the actual schema module on first access."""
        global _module
        if _module is None:
            # Import the actual generated schema module
            from posthog.schema import _generated

            _module = _generated
        return _module

    def __getattr__(name: str):
        """Proxy attribute access to the actual schema module."""
        return getattr(_get_module(), name)

    def __dir__() -> list[str]:
        """Make dir() work correctly with the proxy."""
        return dir(_get_module())

    # Make the module appear to have the same __all__ as the generated module
    # This will be set after first import
    __all__: list[str] | None = None
