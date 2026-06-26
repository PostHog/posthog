"""Test-support surface for core tests that exercise the async-migration engine.

Core tests for the API, tasks, and management command drive the engine using a canonical
example migration and a row factory. They are sanctioned cross-boundary test helpers, kept
out of `api.py` so the production surface stays clean.
"""

from products.async_migrations.backend.examples.test_migration import Migration
from products.async_migrations.backend.test.util import create_async_migration

__all__ = ["Migration", "create_async_migration"]
