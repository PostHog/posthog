"""
Model-class wiring for cdp.

Re-exports the HogFunction model surface cross-product consumers dispatch on. Light.
"""

from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionState, HogFunctionType

__all__ = ["HogFunction", "HogFunctionState", "HogFunctionType"]
