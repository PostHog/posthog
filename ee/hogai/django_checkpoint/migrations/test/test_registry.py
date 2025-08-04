from ee.hogai.django_checkpoint.migrations._0001_add_version_metadata import Migration0001
from ee.hogai.django_checkpoint.migrations.registry import registry


class TestMigrationRegistry:
    """Test the migration registry functionality."""

    def test_registry_version_detection(self):
        """Test that registry correctly detects migration versions."""
        # Migration0001 should have version 1
        assert Migration0001.get_version() == 1

    def test_registry_current_version(self):
        """Test registry tracks current version."""
        # Ensure Migration0001 is registered
        if Migration0001 not in registry._migrations.values():
            registry.register_migration(Migration0001)

        assert registry.current_version >= 1

    def test_registry_get_migrations_needed(self):
        """Test getting migrations needed from a version."""
        # Ensure Migration0001 is registered
        if Migration0001 not in registry._migrations.values():
            registry.register_migration(Migration0001)

        # From version 0, should need Migration0001
        migrations = registry.get_migrations_needed(from_version=0)
        assert Migration0001 in migrations

        # From version 1, should need nothing (if only Migration0001 exists)
        migrations = registry.get_migrations_needed(from_version=1)
        if registry.current_version == 1:
            assert len(migrations) == 0

    def test_get_checkpoint_version(self):
        """Test getting version from checkpoint metadata."""
        # Test with no metadata
        assert registry.get_checkpoint_version({}) == 0

        # Test with empty version_metadata
        assert registry.get_checkpoint_version({"version_metadata": {}}) == 0

        # Test with version
        metadata = {
            "version_metadata": {
                "schema_version": 5,
                "migrated_at": "2024-01-01",
                "graph_type": "assistant",
                "context": "root",
            }
        }
        assert registry.get_checkpoint_version(metadata) == 5
