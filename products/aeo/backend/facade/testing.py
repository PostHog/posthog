"""Test-support facade for aeo.

Outside test suites plant prompts and citation checks through this module so
they never import the product's models or its test factories directly.
"""

from products.aeo.backend.test.factories import create_citation_check, create_prompt

__all__ = ["create_citation_check", "create_prompt"]
