#!/usr/bin/env python3
"""Unit tests for file_handlers.py - testing handler classes and file movement primitives."""

from pathlib import Path

import pytest

from file_handlers import DefaultFileHandler, FileTransformContext, HandlerFactory, ModelsDirectoryHandler


class TestFileTransformContext:
    """Test FileTransformContext dataclass."""

    def test_context_creation(self):
        """Test creating a context with all required fields."""
        context = FileTransformContext(
            model_names={"Model1", "Model2"},
            target_app="test_app",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=Path("/fake/root"),
            model_to_filename_mapping={"Model1": "model1", "Model2": "model2"},
        )

        assert context.model_names == {"Model1", "Model2"}
        assert context.target_app == "test_app"
        assert context.import_base_path == "posthog.warehouse"
        assert context.source_base_path == "posthog/warehouse"
        assert context.root_dir == Path("/fake/root")
        assert context.model_to_filename_mapping == {"Model1": "model1", "Model2": "model2"}


class TestModelsDirectoryHandler:
    """Test ModelsDirectoryHandler strips models/ prefix."""

    def setup_method(self):
        """Set up test context."""
        self.context = FileTransformContext(
            model_names={"DataWarehouseTable"},
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=Path("/fake/root"),
            model_to_filename_mapping={"DataWarehouseTable": "table"},
        )
        self.handler = ModelsDirectoryHandler(self.context)

    def test_compute_target_path_single_file(self):
        """Test models/table.py → backend/models/table.py."""
        target = self.handler.compute_target_path(
            source_file="models/table.py", backend_dir=Path("products/data_warehouse/backend")
        )

        assert target == Path("products/data_warehouse/backend/models/table.py")

    def test_compute_target_path_nested_file(self):
        """Test models/test/test_table.py → backend/models/test/test_table.py."""
        target = self.handler.compute_target_path(
            source_file="models/test/test_table.py", backend_dir=Path("products/data_warehouse/backend")
        )

        assert target == Path("products/data_warehouse/backend/models/test/test_table.py")

    def test_should_apply_db_table(self):
        """Test that db_table should be applied to model files."""
        assert self.handler.should_apply_db_table("models/table.py") is True
        assert self.handler.should_apply_db_table("models/test/test_table.py") is True


class TestDefaultFileHandler:
    """Test DefaultFileHandler preserves file structure at backend level."""

    def setup_method(self):
        """Set up test context."""
        self.context = FileTransformContext(
            model_names=set(),
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=Path("/fake/root"),
            model_to_filename_mapping={},
        )
        self.handler = DefaultFileHandler(self.context)

    def test_compute_target_path_root_file(self):
        """Test hogql.py → backend/hogql.py."""
        target = self.handler.compute_target_path(
            source_file="hogql.py", backend_dir=Path("products/data_warehouse/backend")
        )

        assert target == Path("products/data_warehouse/backend/hogql.py")

    def test_compute_target_path_api_file(self):
        """Test api/saved_query.py → backend/api/saved_query.py."""
        target = self.handler.compute_target_path(
            source_file="api/saved_query.py", backend_dir=Path("products/data_warehouse/backend")
        )

        assert target == Path("products/data_warehouse/backend/api/saved_query.py")

    def test_compute_target_path_data_load_file(self):
        """Test data_load/service.py → backend/data_load/service.py."""
        target = self.handler.compute_target_path(
            source_file="data_load/service.py", backend_dir=Path("products/data_warehouse/backend")
        )

        assert target == Path("products/data_warehouse/backend/data_load/service.py")

    def test_compute_target_path_nested_test_file(self):
        """Test api/test/test_saved_query.py → backend/api/test/test_saved_query.py."""
        target = self.handler.compute_target_path(
            source_file="api/test/test_saved_query.py", backend_dir=Path("products/data_warehouse/backend")
        )

        assert target == Path("products/data_warehouse/backend/api/test/test_saved_query.py")

    def test_should_not_apply_db_table(self):
        """Test that db_table should NOT be applied to non-model files."""
        assert self.handler.should_apply_db_table("hogql.py") is False
        assert self.handler.should_apply_db_table("api/saved_query.py") is False
        assert self.handler.should_apply_db_table("data_load/service.py") is False


class TestHandlerFactory:
    """Test HandlerFactory selects correct handler based on file path."""

    def setup_method(self):
        """Set up test context."""
        self.context = FileTransformContext(
            model_names={"DataWarehouseTable"},
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=Path("/fake/root"),
            model_to_filename_mapping={},
        )

    def test_creates_models_directory_handler_for_models_files(self):
        """Test factory creates ModelsDirectoryHandler for models/ files."""
        handler = HandlerFactory.create_handler("models/table.py", self.context)
        assert isinstance(handler, ModelsDirectoryHandler)

    def test_creates_models_directory_handler_for_nested_models_files(self):
        """Test factory creates ModelsDirectoryHandler for models/test/ files."""
        handler = HandlerFactory.create_handler("models/test/test_table.py", self.context)
        assert isinstance(handler, ModelsDirectoryHandler)

    def test_creates_default_handler_for_api_files(self):
        """Test factory creates DefaultFileHandler for api/ files."""
        handler = HandlerFactory.create_handler("api/saved_query.py", self.context)
        assert isinstance(handler, DefaultFileHandler)

    def test_creates_default_handler_for_data_load_files(self):
        """Test factory creates DefaultFileHandler for data_load/ files."""
        handler = HandlerFactory.create_handler("data_load/service.py", self.context)
        assert isinstance(handler, DefaultFileHandler)

    def test_creates_default_handler_for_test_files(self):
        """Test factory creates DefaultFileHandler for test/ files."""
        handler = HandlerFactory.create_handler("test/utils.py", self.context)
        assert isinstance(handler, DefaultFileHandler)

    def test_creates_default_handler_for_root_files(self):
        """Test factory creates DefaultFileHandler for root-level files."""
        handler = HandlerFactory.create_handler("hogql.py", self.context)
        assert isinstance(handler, DefaultFileHandler)

        handler = HandlerFactory.create_handler("s3.py", self.context)
        assert isinstance(handler, DefaultFileHandler)


class TestHandlerIntegration:
    """Integration tests for complete file processing."""

    def test_models_directory_handler_path_transformation(self):
        """Test complete path transformation for models/ files."""
        context = FileTransformContext(
            model_names={"DataWarehouseTable"},
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=Path("/fake/root"),
            model_to_filename_mapping={"DataWarehouseTable": "table"},
        )

        # Test various models/ files
        test_cases = [
            ("models/table.py", "products/data_warehouse/backend/models/table.py"),
            (
                "models/external_data_source.py",
                "products/data_warehouse/backend/models/external_data_source.py",
            ),
            ("models/test/test_table.py", "products/data_warehouse/backend/models/test/test_table.py"),
        ]

        for source_file, expected_target in test_cases:
            handler = HandlerFactory.create_handler(source_file, context)
            target = handler.compute_target_path(
                source_file=source_file, backend_dir=Path("products/data_warehouse/backend")
            )
            assert str(target) == expected_target, f"Failed for {source_file}"

    def test_default_handler_path_transformation(self):
        """Test complete path transformation for non-models files."""
        context = FileTransformContext(
            model_names=set(),
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=Path("/fake/root"),
            model_to_filename_mapping={},
        )

        # Test various subdirectory files
        test_cases = [
            ("api/saved_query.py", "products/data_warehouse/backend/api/saved_query.py"),
            ("api/test/test_saved_query.py", "products/data_warehouse/backend/api/test/test_saved_query.py"),
            ("data_load/service.py", "products/data_warehouse/backend/data_load/service.py"),
        ]

        for source_file, expected_target in test_cases:
            handler = HandlerFactory.create_handler(source_file, context)
            target = handler.compute_target_path(
                source_file=source_file, backend_dir=Path("products/data_warehouse/backend")
            )
            assert str(target) == expected_target, f"Failed for {source_file}"


class TestIntegrationWithRealFiles:
    """Integration test with real file operations using tmp_path."""

    def test_move_single_file_and_verify_location(self, tmp_path):
        """Test moving a single model file to correct target location."""
        # Setup: Create source file structure
        source_dir = tmp_path / "posthog" / "warehouse"
        models_dir = source_dir / "models"
        models_dir.mkdir(parents=True)

        source_file = models_dir / "table.py"
        source_file.write_text("""from django.db import models

class DataWarehouseTable(models.Model):
    name = models.CharField(max_length=255)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
""")

        # Setup: Create target directory
        target_dir = tmp_path / "products" / "data_warehouse" / "backend"
        target_dir.mkdir(parents=True)

        # Setup: Create context
        context = FileTransformContext(
            model_names={"DataWarehouseTable"},
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=tmp_path,
            model_to_filename_mapping={"DataWarehouseTable": "table"},
        )

        # Execute: Move the file using handler
        handler = HandlerFactory.create_handler("models/table.py", context)
        target_path = handler.compute_target_path("models/table.py", target_dir)

        # Manually copy to simulate the move (without LibCST transformation)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(source_file.read_text())

        # Verify: File exists at correct location
        assert target_path.exists()
        expected_path = tmp_path / "products" / "data_warehouse" / "backend" / "models" / "table.py"
        assert target_path == expected_path
        assert "DataWarehouseTable" in target_path.read_text()

    def test_multiple_file_types_to_correct_locations(self, tmp_path):
        """Test that different file types go to their correct backend/ subdirectories."""
        # Setup: Create source directory structure
        source_dir = tmp_path / "posthog" / "warehouse"

        # Create models/ file
        models_dir = source_dir / "models"
        models_dir.mkdir(parents=True)
        (models_dir / "table.py").write_text("class Table: pass")

        # Create api/ file
        api_dir = source_dir / "api"
        api_dir.mkdir(parents=True)
        (api_dir / "saved_query.py").write_text("class SavedQueryViewSet: pass")

        # Create data_load/ file
        data_load_dir = source_dir / "data_load"
        data_load_dir.mkdir(parents=True)
        (data_load_dir / "service.py").write_text("def load_data(): pass")

        # Create root-level file
        (source_dir / "hogql.py").write_text("def parse(): pass")

        # Setup: Create target directory
        target_dir = tmp_path / "products" / "data_warehouse" / "backend"
        target_dir.mkdir(parents=True)

        # Setup: Create context
        context = FileTransformContext(
            model_names={"Table"},
            target_app="data_warehouse",
            import_base_path="posthog.warehouse",
            source_base_path="posthog/warehouse",
            root_dir=tmp_path,
            model_to_filename_mapping={},
        )

        # Test cases: (source_file, expected_relative_target)
        test_cases = [
            ("models/table.py", "models/table.py"),
            ("api/saved_query.py", "api/saved_query.py"),
            ("data_load/service.py", "data_load/service.py"),
            ("hogql.py", "hogql.py"),
        ]

        for source_file, expected_relative in test_cases:
            # Execute: Get handler and compute target
            handler = HandlerFactory.create_handler(source_file, context)
            target_path = handler.compute_target_path(source_file, target_dir)

            # Verify: Path is correct
            expected_full_path = target_dir / expected_relative
            assert (
                target_path == expected_full_path
            ), f"Failed for {source_file}: expected {expected_full_path}, got {target_path}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
