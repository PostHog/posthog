"""Test-support facade for aeo.

Outside test suites plant citation checks through this module so they never
import the product's models or its test factories directly.
"""

from products.aeo.backend.test.factories import create_citation_check

__all__ = ["create_citation_check"]
