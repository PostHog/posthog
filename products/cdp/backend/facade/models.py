"""
Model-class wiring for cdp.

Re-exports the HogFunction model surface cross-product consumers dispatch on. Light.
"""

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionState, HogFunctionType

__all__ = ["HogFunction", "HogFunctionState", "HogFunctionTemplate", "HogFunctionType"]
