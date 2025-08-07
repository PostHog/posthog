import pytest
from ee.hogai.django_checkpoint.migrations.migration_registry import MigrationRegistry
from ee.hogai.django_checkpoint.migrations.base import BaseMigration
from ee.hogai.django_checkpoint.context import CheckpointContext
from ee.hogai.utils.types import GraphContext, GraphType


class TestMigrationRegistry:
    @pytest.mark.parametrize(
        "version,field_name,field_value,expected",
        [
            (1, "field1", "value1", "value1"),
            (2, "field2", "value2", "value2"),
            (5, "field5", "value5", "value5"),
            (10, "field10", "value10", "value10"),
        ],
    )
    def test_migration_registration_and_retrieval(self, version, field_name, field_value, expected):
        """Test migration registration with different versions."""
        registry = MigrationRegistry()

        # Create migration class dynamically
        migration_class = type(
            f"Migration{version}",
            (BaseMigration,),
            {
                "migrate_data": lambda self, data, type_hint, context=None: (
                    {**data, field_name: field_value},
                    type_hint,
                )
            },
        )

        # Register and verify
        registry._migrations[version] = migration_class
        assert version in registry._migrations
        assert registry._migrations[version] == migration_class

        # Test migration application
        data = {"original": "data"}
        migration = migration_class()
        result, _ = migration.migrate_data(
            data, "TestType", context=CheckpointContext(graph_type=GraphType.ASSISTANT, graph_context=GraphContext.ROOT)
        )
        assert result[field_name] == expected
        assert result["original"] == "data"

    def test_register_migration(self):
        """Test registering a migration."""
        registry = MigrationRegistry()

        # Create a migration class dynamically
        migration_class = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )

        registry.register_migration(migration_class)

        assert 1 in registry._migrations
        assert registry._migrations[1] == migration_class
        assert registry.current_version == 1

    def test_register_multiple_migrations(self):
        """Test registering multiple migrations."""
        registry = MigrationRegistry()

        # Create migration classes dynamically
        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration2 = type(
            "Migration2",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0002_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration3 = type(
            "Migration3",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0003_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )

        registry.register_migration(migration1)
        registry.register_migration(migration3)
        registry.register_migration(migration2)

        assert len(registry._migrations) == 3
        assert registry.current_version == 3
        assert registry._migrations[1] == migration1
        assert registry._migrations[2] == migration2
        assert registry._migrations[3] == migration3

    def test_register_duplicate_version_warns(self):
        """Test that registering duplicate version warns."""
        registry = MigrationRegistry()

        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_first",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration2 = type(
            "Migration2",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_duplicate",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )

        registry.register_migration(migration1)
        # Second registration should work but warn (not raise)
        registry.register_migration(migration2)

        # The second one should have overwritten
        assert registry._migrations[1] == migration2

    def test_get_migrations_needed_from_zero(self):
        """Test getting migrations needed from version 0."""
        registry = MigrationRegistry()

        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration2 = type(
            "Migration2",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0002_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration3 = type(
            "Migration3",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0003_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )

        registry.register_migration(migration1)
        registry.register_migration(migration2)
        registry.register_migration(migration3)

        migrations = registry.get_migrations_needed(from_version=0)

        assert len(migrations) == 3
        assert migrations[0] == migration1
        assert migrations[1] == migration2
        assert migrations[2] == migration3

    def test_get_migrations_needed_partial(self):
        """Test getting migrations needed from intermediate version."""
        registry = MigrationRegistry()

        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration2 = type(
            "Migration2",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0002_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        migration3 = type(
            "Migration3",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0003_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )

        registry.register_migration(migration1)
        registry.register_migration(migration2)
        registry.register_migration(migration3)

        # From version 1, need migrations 2 and 3
        migrations = registry.get_migrations_needed(from_version=1)
        assert len(migrations) == 2
        assert migrations[0] == migration2
        assert migrations[1] == migration3

        # From version 2, need only migration 3
        migrations = registry.get_migrations_needed(from_version=2)
        assert len(migrations) == 1
        assert migrations[0] == migration3

    def test_get_migrations_needed_none_needed(self):
        """Test when no migrations are needed."""
        registry = MigrationRegistry()

        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint, context=None: (data, type_hint),
            },
        )
        registry.register_migration(migration1)

        # Already at current version
        migrations = registry.get_migrations_needed(from_version=1)
        assert migrations == []

        # Beyond current version
        migrations = registry.get_migrations_needed(from_version=2)
        assert migrations == []

    # Removed tests for get_checkpoint_version as it doesn't exist in MigrationRegistry

    def test_current_version_updates(self):
        """Test that current_version updates as migrations are added."""
        registry = MigrationRegistry()
        assert registry.current_version == 1  # Starts at 1

        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        registry.register_migration(migration1)
        assert registry.current_version == 1

        migration5 = type(
            "Migration5",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0005_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        registry.register_migration(migration5)
        assert registry.current_version == 5

        migration3 = type(
            "Migration3",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0003_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        registry.register_migration(migration3)
        assert registry.current_version == 5  # Still 5, not 3

    def test_migrations_ordered_correctly(self):
        """Test that migrations are returned in version order."""
        registry = MigrationRegistry()

        # Register out of order
        migration3 = type(
            "Migration3",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0003_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        migration2 = type(
            "Migration2",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0002_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )

        registry.register_migration(migration3)
        registry.register_migration(migration1)
        registry.register_migration(migration2)

        migrations = registry.get_migrations_needed(from_version=0)

        # Should be ordered 1, 2, 3
        assert migrations[0] == migration1
        assert migrations[1] == migration2
        assert migrations[2] == migration3

    def test_apply_migrations_chain(self):
        """Test that migrations can be chained."""
        registry = MigrationRegistry()

        # Create migrations that add different fields
        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint, context=None: ({**data, "field1": "value1"}, type_hint),
            },
        )
        migration2 = type(
            "Migration2",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0002_test",
                "migrate_data": lambda self, data, type_hint, context=None: ({**data, "field2": "value2"}, type_hint),
            },
        )

        registry.register_migration(migration1)
        registry.register_migration(migration2)

        # Apply migrations in sequence
        data = {"original": "value"}
        type_hint = "TestType"

        migrations = registry.get_migrations_needed(from_version=0)

        for migration_class in migrations:
            migration = migration_class()
            data, type_hint = migration.migrate_data(data, type_hint, context=None)

        # Both migrations should have been applied
        assert data["field1"] == "value1"
        assert data["field2"] == "value2"
        assert data["original"] == "value"  # Original data preserved

    def test_non_sequential_versions(self):
        """Test registry with non-sequential version numbers."""
        registry = MigrationRegistry()

        migration1 = type(
            "Migration1",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        migration5 = type(
            "Migration5",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0005_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )
        migration10 = type(
            "Migration10",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0010_test",
                "migrate_data": lambda self, data, type_hint: (data, type_hint),
            },
        )

        registry.register_migration(migration1)
        registry.register_migration(migration5)
        registry.register_migration(migration10)

        assert registry.current_version == 10

        migrations = registry.get_migrations_needed(from_version=0)
        assert len(migrations) == 3
        assert migrations[0] == migration1
        assert migrations[1] == migration5
        assert migrations[2] == migration10

    def test_migration_with_type_change(self):
        """Test migration that changes the type hint."""
        registry = MigrationRegistry()

        # Create migration class that changes type
        TypeChangeMigration = type(
            "TypeChangeMigration",
            (BaseMigration,),
            {
                "__module__": "test.migrations._0001_type_change",
                "migrate_data": lambda self, data, type_hint: (
                    data,
                    "NewType" if type_hint == "OldType" else type_hint,
                ),
            },
        )

        registry.register_migration(TypeChangeMigration)

        data = {"field": "value"}
        type_hint = "OldType"

        migrations = registry.get_migrations_needed(from_version=0)
        for migration_class in migrations:
            migration = migration_class()
            data, type_hint = migration.migrate_data(data, type_hint, context=None)

        assert type_hint == "NewType"
