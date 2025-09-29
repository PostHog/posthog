#!/usr/bin/env python3
"""
Unit tests for the ImportTransformer LibCST class in migrate_models.py

Tests both existing functionality and new sub-module import handling.
"""

import sys
from pathlib import Path

import pytest
from unittest.mock import patch

import libcst as cst

# Add the model_migration directory to the path so we can import the module
sys.path.insert(0, str(Path(__file__).parent))

from migrate_models import ImportTransformer, ModelMigrator


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

    def test_subdirectory_main_file_import_transformation(self):
        """Test: from posthog.models.error_tracking.error_tracking import ... → products.error_tracking.backend.models"""
        source = "from posthog.models.error_tracking.error_tracking import ErrorTrackingIssue"
        expected = "from products.error_tracking.backend.models import ErrorTrackingIssue"
        result, changed = self._transform_code(source)
        assert changed is True, f"Expected transformation but got unchanged result: {result}"
        assert expected.strip() in result.strip(), f"Expected: {expected}\nGot: {result}"


class TestForeignKeyReferences:
    """Test the foreign key reference updates"""

    def test_direct_foreign_key_to_string_conversion(self):
        """Test: ForeignKey(Team, ...) → ForeignKey("posthog.Team", ...)"""
        from unittest.mock import patch

        from migrate_models import ModelMigrator

        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            migrator = ModelMigrator("dummy_config.json")

        model_names = {"ErrorTrackingIssue"}  # Models being moved

        # Test ForeignKey conversion
        source = "    team = models.ForeignKey(Team, on_delete=models.CASCADE)"
        expected = '    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)'
        result = migrator._update_foreign_key_references(source, model_names)
        assert result == expected, f"Expected: {expected}\nGot: {result}"

    def test_direct_many_to_many_field_conversion(self):
        """Test: ManyToManyField(User) → ManyToManyField("posthog.User")"""
        from unittest.mock import patch

        from migrate_models import ModelMigrator

        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            migrator = ModelMigrator("dummy_config.json")

        model_names = {"ErrorTrackingIssue"}

        source = "    users = models.ManyToManyField(User)"
        expected = '    users = models.ManyToManyField("posthog.User")'
        result = migrator._update_foreign_key_references(source, model_names)
        assert result == expected, f"Expected: {expected}\nGot: {result}"

    def test_direct_one_to_one_field_conversion(self):
        """Test: OneToOneField(Team, ...) → OneToOneField("posthog.Team", ...)"""
        from unittest.mock import patch

        from migrate_models import ModelMigrator

        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            migrator = ModelMigrator("dummy_config.json")

        model_names = {"ErrorTrackingIssue"}

        source = "    team_config = models.OneToOneField(Team, on_delete=models.CASCADE)"
        expected = '    team_config = models.OneToOneField("posthog.Team", on_delete=models.CASCADE)'
        result = migrator._update_foreign_key_references(source, model_names)
        assert result == expected, f"Expected: {expected}\nGot: {result}"

    def test_do_not_convert_moved_models(self):
        """Test that direct references to models being moved are not converted"""
        from unittest.mock import patch

        from migrate_models import ModelMigrator

        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            migrator = ModelMigrator("dummy_config.json")

        model_names = {"ErrorTrackingSymbolSet"}  # This model is being moved

        source = "    symbol_set = models.ForeignKey(ErrorTrackingSymbolSet, on_delete=models.SET_NULL)"
        result = migrator._update_foreign_key_references(source, model_names)
        assert result == source, f"Expected unchanged: {source}\nGot: {result}"

    def test_existing_string_references_unchanged(self):
        """Test that existing string references work as before"""
        from unittest.mock import patch

        from migrate_models import ModelMigrator

        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            migrator = ModelMigrator("dummy_config.json")

        model_names = {"ErrorTrackingIssue"}

        # Already has posthog prefix - should not change
        source = '    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)'
        result = migrator._update_foreign_key_references(source, model_names)
        assert result == source, f"Expected unchanged: {source}\nGot: {result}"

    def test_non_foreign_key_lines_unchanged(self):
        """Test that non-FK lines are not affected"""
        from unittest.mock import patch

        from migrate_models import ModelMigrator

        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            migrator = ModelMigrator("dummy_config.json")

        model_names = {"ErrorTrackingIssue"}

        source = "    name = models.CharField(max_length=255)"
        result = migrator._update_foreign_key_references(source, model_names)
        assert result == source, f"Expected unchanged: {source}\nGot: {result}"


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


class TestSubdirectoryExpansion:
    """Test the subdirectory expansion and file movement logic"""

    def setup_method(self):
        """Set up test migrator instance"""
        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            self.migrator = ModelMigrator("dummy_config.json")
            self.migrator.root_dir = Path("/fake/root")

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("pathlib.Path.rglob")
    def test_expand_subdirectory_files(self, mock_rglob, mock_is_dir, mock_exists):
        """Test expansion of subdirectory to include all Python files"""
        # Mock directory structure:
        # posthog/models/error_tracking/
        #   ├── error_tracking.py (main model file)
        #   ├── sql.py (supporting file)
        #   ├── hogvm_stl.py (supporting file)
        #   ├── __init__.py (skip this)
        #   └── test/
        #       └── test_error_tracking.py (test file)

        # Mock the directory existence and structure
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        # Mock the files found by rglob
        mock_files = [
            Path("/fake/root/posthog/models/error_tracking/error_tracking.py"),
            Path("/fake/root/posthog/models/error_tracking/sql.py"),
            Path("/fake/root/posthog/models/error_tracking/hogvm_stl.py"),
            Path("/fake/root/posthog/models/error_tracking/__init__.py"),  # Should be skipped
            Path("/fake/root/posthog/models/error_tracking/test/test_error_tracking.py"),
        ]
        mock_rglob.return_value = mock_files

        # Test the expansion
        source_files = ["error_tracking/error_tracking.py"]
        expanded_files, non_model_files = self.migrator._expand_subdirectory_files(source_files)

        # Verify results
        expected_expanded = [
            "error_tracking/error_tracking.py",
            "error_tracking/sql.py",
            "error_tracking/hogvm_stl.py",
            "error_tracking/test/test_error_tracking.py",
        ]
        expected_non_model = [
            "error_tracking/sql.py",
            "error_tracking/hogvm_stl.py",
            "error_tracking/test/test_error_tracking.py",
        ]

        assert set(expanded_files) == set(expected_expanded)
        assert set(non_model_files) == set(expected_non_model)

    def test_expand_regular_files(self):
        """Test that regular (non-subdirectory) files are passed through unchanged"""
        source_files = ["experiment.py", "web_experiment.py"]
        expanded_files, non_model_files = self.migrator._expand_subdirectory_files(source_files)

        assert expanded_files == source_files
        assert non_model_files == []

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    def test_expand_nonexistent_subdirectory(self, mock_is_dir, mock_exists):
        """Test handling of subdirectory that doesn't exist"""
        mock_exists.return_value = False
        mock_is_dir.return_value = False

        source_files = ["nonexistent/model.py"]
        expanded_files, non_model_files = self.migrator._expand_subdirectory_files(source_files)

        # Should fall back to original file
        assert expanded_files == source_files
        assert non_model_files == []


class TestFileMovement:
    """Test the actual file movement logic"""

    def setup_method(self):
        """Set up test migrator instance"""
        with patch.object(ModelMigrator, "load_config", return_value={"migrations": []}):
            self.migrator = ModelMigrator("dummy_config.json")
            self.migrator.root_dir = Path("/fake/root")

    @patch("os.remove")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.exists")
    @patch.object(ModelMigrator, "_expand_subdirectory_files")
    @patch.object(ModelMigrator, "_extract_class_names_from_files")
    @patch.object(ModelMigrator, "_ensure_model_db_tables")
    @patch.object(ModelMigrator, "_update_imports_for_module")
    @patch("builtins.open", create=True)
    def test_move_subdirectory_files(
        self,
        mock_open,
        mock_update_imports,
        mock_ensure_tables,
        mock_extract_classes,
        mock_expand_files,
        mock_exists,
        mock_mkdir,
        mock_move,
        mock_remove,
    ):
        """Test complete file movement for subdirectory structure"""
        # Setup mocks
        mock_expand_files.return_value = (
            ["error_tracking/error_tracking.py", "error_tracking/sql.py", "error_tracking/test/test_error_tracking.py"],
            ["error_tracking/sql.py", "error_tracking/test/test_error_tracking.py"],
        )
        mock_extract_classes.return_value = {"ErrorTrackingIssue", "ErrorTrackingStackFrame"}
        mock_exists.return_value = True

        # Mock file content for models.py creation
        mock_file_content = "from django.db import models\n\nclass ErrorTrackingIssue(models.Model):\n    pass\n"
        mock_open.return_value.__enter__.return_value.read.return_value = mock_file_content

        # Call the method
        result = self.migrator.move_model_files_and_update_imports(
            ["error_tracking/error_tracking.py"], "error_tracking"
        )

        # Verify expansion was called
        mock_expand_files.assert_called_once_with(["error_tracking/error_tracking.py"])

        # Verify supporting files were moved
        assert mock_move.call_count == 2  # sql.py and test_error_tracking.py

        # Verify directory creation for test folder
        mock_mkdir.assert_called()

        # Verify import updates were called
        mock_update_imports.assert_called()

        assert result is True


if __name__ == "__main__":
    # Run with: python test_import_transformer.py
    pytest.main([__file__, "-v"])
