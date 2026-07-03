"""
Facade for cdp.

Re-exports the HogFunction serializer cross-product API views reuse. Lazy (PEP 562) to
keep the DRF/serializer import chain off config-only import paths.
"""

_B = "products.cdp.backend."

_LAZY = {"HogFunctionSerializer": "api.hog_function"}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
