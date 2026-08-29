"""Test-support facade for customer_analytics.

Sibling products' tests plant accounts through this module so they never import the
product's model or its test factories directly.
"""

from products.customer_analytics.backend.test.factories import create_account

__all__ = ["create_account"]
