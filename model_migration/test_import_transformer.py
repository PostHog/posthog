#!/usr/bin/env python3
"""
Unit tests for the ImportTransformer LibCST class in migrate_models.py

Tests both existing functionality and new sub-module import handling.
"""

import sys
from pathlib import Path

import pytest

import libcst as cst

# Add the model_migration directory to the path so we can import the module
sys.path.insert(0, str(Path(__file__).parent))

from migrate_models import ImportTransformer


class TestImportTransformer:
    """Test the LibCST ImportTransformer class"""

    def setup_method(self):
        """Set up test data before each test"""
        self.model_names = {
            "ErrorTrackingIssue",
            "ErrorTrackingIssueFingerprintV2",
            "ErrorTrackingStackFrame",
            "ErrorTrackingSymbolSet",
        }
        self.target_app = "error_tracking"
        self.module_name = "error_tracking/error_tracking"  # Subdirectory case

    def _transform_code(self, source_code: str) -> tuple[str, bool]:
        """Helper to transform Python code and return (result, changed)"""
        tree = cst.parse_module(source_code)
        transformer = ImportTransformer(self.model_names, self.target_app, self.module_name)
        new_tree = tree.visit(transformer)
        return new_tree.code, transformer.changed

    def test_general_import_transformation(self):
        """Test: from posthog.models import ... → products.error_tracking.backend.models"""
        source = "from posthog.models import ErrorTrackingIssue, Team"
        result, changed = self._transform_code(source)
        assert changed is True
        assert "from products.error_tracking.backend.models import ErrorTrackingIssue" in result
        assert "from posthog.models import Team" in result

    def test_direct_module_import_transformation(self):
        """Test: from posthog.models.error_tracking import ... → products.error_tracking.backend.models"""
        source = "from posthog.models.error_tracking import ErrorTrackingIssue, ErrorTrackingStackFrame"
        expected = "from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingStackFrame"
        result, changed = self._transform_code(source)
        assert changed is True
        assert expected.strip() in result.strip()

    def test_sub_module_sql_import_transformation(self):
        """Test: from posthog.models.error_tracking.sql import ... → products.error_tracking.backend.sql"""
        source = "from posthog.models.error_tracking.sql import INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES"
        expected = "from products.error_tracking.backend.sql import INSERT_ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES"
        result, changed = self._transform_code(source)
        assert changed is True, f"Expected transformation but got unchanged result: {result}"
        assert expected.strip() in result.strip(), f"Expected: {expected}\nGot: {result}"

    def test_sub_module_hogvm_stl_import_transformation(self):
        """Test: from posthog.models.error_tracking.hogvm_stl import ... → products.error_tracking.backend.hogvm_stl"""
        source = "from posthog.models.error_tracking.hogvm_stl import RUST_HOGVM_STL"
        expected = "from products.error_tracking.backend.hogvm_stl import RUST_HOGVM_STL"
        result, changed = self._transform_code(source)
        assert changed is True, f"Expected transformation but got unchanged result: {result}"
        assert expected.strip() in result.strip(), f"Expected: {expected}\nGot: {result}"

    def test_non_matching_imports_unchanged(self):
        """Test that non-matching imports are left unchanged"""
        source = "from django.db import models"
        result, changed = self._transform_code(source)
        assert changed is False
        assert result.strip() == source.strip()

    def test_non_error_tracking_posthog_imports_unchanged(self):
        """Test that other posthog.models imports are unchanged"""
        source = "from posthog.models.team import Team"
        result, changed = self._transform_code(source)
        assert changed is False
        assert result.strip() == source.strip()

    def test_complex_multiline_import(self):
        """Test complex multiline import with mixed models"""
        source = """from posthog.models.error_tracking import (
    ErrorTrackingIssue,
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
)"""
        expected_part = "from products.error_tracking.backend.models import"
        result, changed = self._transform_code(source)
        assert changed is True
        assert expected_part in result
        assert "ErrorTrackingIssue" in result
        assert "ErrorTrackingStackFrame" in result


class TestDirectFileModule:
    """Test with direct file (non-subdirectory) module for comparison"""

    def test_direct_file_module(self):
        """Test with a direct file module (not subdirectory)"""
        model_names = {"Experiment"}
        target_app = "experiments"
        module_name = "experiment"  # Direct file, not subdirectory

        source = "from posthog.models.experiment import Experiment"
        expected = "from products.experiments.backend.models import Experiment"

        tree = cst.parse_module(source)
        transformer = ImportTransformer(model_names, target_app, module_name)
        new_tree = tree.visit(transformer)

        assert transformer.changed is True
        assert expected.strip() in new_tree.code.strip()


if __name__ == "__main__":
    # Run with: python test_import_transformer.py
    pytest.main([__file__, "-v"])
