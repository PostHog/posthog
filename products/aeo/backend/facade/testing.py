"""Test-support facade for aeo.

Outside test suites plant citation checks and brands through this module so they never
import the product's models or its test factories directly.
"""

from products.aeo.backend.test.factories import create_brand, create_citation_check

__all__ = ["create_brand", "create_citation_check"]
