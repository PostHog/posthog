"""Light tests for fixture-registry shape.

The factories themselves are exercised end-to-end by
`posthog/test/test_idor_coverage.py`; here we just assert the registry
maps to the right factory functions for the FK targets Phase 5a relies
on. These tests run without a DB.
"""

from __future__ import annotations

import unittest

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.test.idor.fixtures import _REGISTRY_BY_LABEL, get_fixture


class TestFixtureRegistry(unittest.TestCase):
    def test_integration_factory_registered(self) -> None:
        assert get_fixture(Integration) is not None, "Integration fixture should be registered"

    def test_organization_membership_factory_registered(self) -> None:
        assert get_fixture(OrganizationMembership) is not None, "OrganizationMembership fixture should be registered"

    def test_registry_keys_are_app_dot_modelname(self) -> None:
        for key in _REGISTRY_BY_LABEL:
            assert "." in key, f"registry key {key!r} should be app_label.ModelName"


if __name__ == "__main__":
    unittest.main()
