"""Sanity tests for the CI coverage check machinery.

These tests verify that skip_list entries are well-formed and cross-reference
actual viewsets. The full CI check (.github/scripts/check-idor-test-coverage.py)
runs in CI; this module tests the invariants the check relies on.
"""

from __future__ import annotations

import unittest

from posthog.test.idor.skip_list import IDOR_TEST_SKIP_LIST


class TestSkipListWellFormed(unittest.TestCase):
    def test_every_entry_has_category_and_reason(self) -> None:
        for name, entry in IDOR_TEST_SKIP_LIST.items():
            assert isinstance(entry, tuple), f"Skip entry for {name!r} must be a (category, reason) tuple"
            assert len(entry) == 2, f"Skip entry for {name!r} must be (category, reason)"
            category, reason = entry
            assert isinstance(category, str) and category, f"{name!r}: category must be a non-empty string"
            assert isinstance(reason, str) and reason, f"{name!r}: reason must be a non-empty string"

    def test_categories_are_from_documented_set(self) -> None:
        # Update this set when adding a new category to the skip_list docstring.
        documented_categories = {
            "AUTO_URL_MISMATCH",
            "LATENT_ERROR_HANDLING_BUG",
            "INTENTIONAL_CROSS_TEAM",
            "RETURNS_200_WITH_EMPTY_AGGREGATION",
            "CUSTOM_MODEL_VALIDATION",
            "CUSTOM_FIELD_TYPE",
            "MUTUALLY_EXCLUSIVE_CONSTRAINTS",
            "COMPLEX_DEPENDENCIES",
            "LATENT_FILTER_REWRITE_BUG",
            "LEGACY_FLAT_URL",
            "CUSTOM_LOOKUP_FIELD",
            "TENANT_ROOT_RESOURCE",
            "NO_MODEL",
        }
        used = {cat for (cat, _) in IDOR_TEST_SKIP_LIST.values()}
        unknown = used - documented_categories
        assert not unknown, (
            f"Skip list uses undocumented categories: {sorted(unknown)}. "
            f"Either add them to the documented set in test_coverage_check.py or fix the skip_list entry."
        )


if __name__ == "__main__":
    unittest.main()
