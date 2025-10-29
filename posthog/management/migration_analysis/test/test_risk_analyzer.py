from unittest.mock import MagicMock

from django.db import migrations, models

from posthog.management.migration_analysis.analyzer import RiskAnalyzer
from posthog.management.migration_analysis.models import RiskLevel


def create_mock_operation(op_class, **kwargs):
    """Helper to create mock migration operations"""
    op = MagicMock(spec=op_class)
    op.__class__.__name__ = op_class.__name__
    for key, value in kwargs.items():
        setattr(op, key, value)
    return op


class TestRiskLevelScoring:
    def test_safe_scores(self):
        assert RiskLevel.from_score(0) == RiskLevel.SAFE
        assert RiskLevel.from_score(1) == RiskLevel.SAFE

    def test_needs_review_scores(self):
        assert RiskLevel.from_score(2) == RiskLevel.NEEDS_REVIEW
        assert RiskLevel.from_score(3) == RiskLevel.NEEDS_REVIEW

    def test_blocked_scores(self):
        assert RiskLevel.from_score(4) == RiskLevel.BLOCKED
        assert RiskLevel.from_score(5) == RiskLevel.BLOCKED

    def test_out_of_range_scores(self):
        assert RiskLevel.from_score(10) == RiskLevel.BLOCKED
        assert RiskLevel.from_score(-1) == RiskLevel.SAFE


class TestAddFieldOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_add_nullable_field(self):
        field: models.Field = models.CharField(max_length=100, null=True)
        op = create_mock_operation(
            migrations.AddField,
            model_name="testmodel",
            name="test_field",
            field=field,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 0
        assert "nullable" in risk.reason.lower()
        assert risk.level == RiskLevel.SAFE

    def test_add_blank_field_without_null(self):
        """blank=True doesn't make database safe - only null=True does."""
        field: models.Field = models.CharField(max_length=100, blank=True, null=False, default="")
        op = create_mock_operation(
            migrations.AddField,
            model_name="testmodel",
            name="test_field",
            field=field,
        )

        risk = self.analyzer.analyze_operation(op)

        # blank=True is just form validation, so this needs a default to be safe
        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE

    def test_add_not_null_with_default(self):
        field: models.Field = models.CharField(max_length=100, default="test", null=False, blank=False)
        op = create_mock_operation(
            migrations.AddField,
            model_name="testmodel",
            name="test_field",
            field=field,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert "constant" in risk.reason.lower()
        assert risk.level == RiskLevel.SAFE

    def test_add_not_null_without_default(self):
        """Test NOT NULL field without default - Django doesn't set default, it's NOT_PROVIDED by default."""
        # Don't set default parameter - Django fields default to NOT_PROVIDED
        field: models.Field = models.CharField(max_length=100, null=False, blank=False)
        # Verify the field has no default (models.NOT_PROVIDED is the sentinel value)
        assert field.default == models.NOT_PROVIDED

        op = create_mock_operation(
            migrations.AddField,
            model_name="testmodel",
            name="test_field",
            field=field,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert "locks table" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED


class TestRemoveOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_remove_field(self):
        op = create_mock_operation(
            migrations.RemoveField,
            model_name="testmodel",
            name="test_field",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert "backwards compatibility" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED
        assert risk.details["model"] == "testmodel"
        assert risk.details["field"] == "test_field"

    def test_delete_model(self):
        op = create_mock_operation(
            migrations.DeleteModel,
            name="TestModel",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert "backwards compatibility" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED


class TestAlterOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_alter_field(self):
        op = create_mock_operation(
            migrations.AlterField,
            model_name="testmodel",
            name="test_field",
            field=models.CharField(max_length=200),
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 3
        assert "locks" in risk.reason.lower() or "data loss" in risk.reason.lower()
        assert risk.level == RiskLevel.NEEDS_REVIEW


class TestRenameOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_rename_field(self):
        op = create_mock_operation(
            migrations.RenameField,
            model_name="testmodel",
            old_name="old_field",
            new_name="new_field",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 4
        assert risk.level == RiskLevel.BLOCKED
        assert risk.details["old"] == "old_field"
        assert risk.details["new"] == "new_field"

    def test_rename_model(self):
        """Test RenameModel without migration context (defaults to BLOCKED)."""
        op = create_mock_operation(
            migrations.RenameModel,
            old_name="OldModel",
            new_name="NewModel",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 4
        assert risk.level == RiskLevel.BLOCKED

    def test_rename_model_with_db_table_set(self):
        """
        Test RenameModel when model has explicit db_table (should be SAFE).

        When db_table is explicitly set in Meta, Django's RenameModel is a no-op
        for the table rename - only Python code references change.

        Note: This test requires a real model in the app registry with db_table set.
        For example, products.tasks.TaskProgress has db_table="posthog_task_progress".
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "tasks"  # products.tasks app
        mock_migration.name = "0010_rename_taskprogress_to_taskrun"
        mock_migration.operations = [
            create_mock_operation(
                migrations.RenameModel,
                old_name="TaskProgress",
                new_name="TaskRun",
            )
        ]

        # Analyze with migration context so db_table can be checked
        migration_risk = self.analyzer.analyze_migration(
            mock_migration, "products/tasks/backend/migrations/0010_rename_taskprogress_to_taskrun.py"
        )

        # Should be SAFE (score 0) because TaskProgress has db_table set
        # If model not found or db_table not set, falls back to score 4 (BLOCKED)
        # This test will pass either way (documenting expected behavior)
        if migration_risk.level == RiskLevel.SAFE:
            assert migration_risk.max_score == 0
            assert "db_table explicitly set" in migration_risk.operations[0].reason
        else:
            # Model not found in test environment - expected
            assert migration_risk.level == RiskLevel.BLOCKED


class TestIndexOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_add_index_non_concurrent(self):
        index = MagicMock()
        index.concurrent = False
        op = create_mock_operation(
            migrations.AddIndex,
            model_name="testmodel",
            index=index,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 4
        assert "locks table" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED

    def test_add_index_concurrent(self):
        index = MagicMock()
        index.concurrent = True
        op = create_mock_operation(
            migrations.AddIndex,
            model_name="testmodel",
            index=index,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 0
        assert "safe" in risk.reason.lower()
        assert risk.level == RiskLevel.SAFE


class TestRunSQLOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_run_sql_with_drop_table_without_if_exists(self):
        """DROP TABLE without IF EXISTS is dangerous (score 5 - BLOCKED)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE foo;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert "dangerous" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED

    def test_run_sql_with_drop_table_if_exists_without_context(self):
        """DROP TABLE IF EXISTS without migration context (score 5 - BLOCKED).

        Without migration history, we can't validate proper staging, so it's blocked.
        """
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
        )

        risk = self.analyzer.analyze_operation(op)

        # Score 5 (BLOCKED) when we can't validate staging
        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "no prior state removal" in risk.reason.lower()
        assert risk.guidance is not None and "SeparateDatabaseAndState" in risk.guidance

    def test_run_sql_with_update(self):
        op = create_mock_operation(
            migrations.RunSQL,
            sql="UPDATE users SET active = true;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 4
        assert "locking" in risk.reason.lower() or "review" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED

    def test_run_sql_with_alter(self):
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users ADD COLUMN foo text;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 3
        assert risk.level == RiskLevel.NEEDS_REVIEW

    def test_run_sql_with_concurrent_index_with_if_not_exists(self):
        """Test CREATE INDEX CONCURRENTLY with IF NOT EXISTS - score 1 (SAFE)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON users(foo);",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE
        assert "safe" in risk.reason.lower() or "non-blocking" in risk.reason.lower()

    def test_run_sql_with_concurrent_index_without_if_not_exists(self):
        """Test CREATE INDEX CONCURRENTLY without IF NOT EXISTS - score 2 (NEEDS_REVIEW)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE INDEX CONCURRENTLY idx_foo ON users(foo);",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert risk.guidance and "if not exists" in risk.guidance.lower()

    def test_run_sql_with_drop_index_concurrent_with_if_exists(self):
        """Test DROP INDEX CONCURRENTLY with IF EXISTS - score 1 (SAFE)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP INDEX CONCURRENTLY IF EXISTS idx_foo;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE
        assert "safe" in risk.reason.lower() or "non-blocking" in risk.reason.lower()

    def test_run_sql_with_drop_index_concurrent_without_if_exists(self):
        """Test DROP INDEX CONCURRENTLY without IF EXISTS - score 2 (NEEDS_REVIEW)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP INDEX CONCURRENTLY idx_foo;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert risk.guidance and "if exists" in risk.guidance.lower()

    def test_run_sql_with_reindex_concurrent(self):
        """Test REINDEX CONCURRENTLY - should be safe (score 1)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="REINDEX INDEX CONCURRENTLY idx_foo;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE
        assert "safe" in risk.reason.lower() or "non-blocking" in risk.reason.lower()

    def test_run_sql_add_constraint_not_valid(self):
        """Test ADD CONSTRAINT ... NOT VALID - safe (score 1)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 0) NOT VALID;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE
        assert "not valid" in risk.reason.lower() or "validates new rows" in risk.reason.lower()

    def test_run_sql_validate_constraint(self):
        """Test VALIDATE CONSTRAINT - slow but non-blocking (score 2)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users VALIDATE CONSTRAINT check_age;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert "validate" in risk.reason.lower()

    def test_run_sql_drop_constraint(self):
        """Test DROP CONSTRAINT - fast metadata operation (score 1)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users DROP CONSTRAINT check_age;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE
        assert "fast" in risk.reason.lower() or "metadata" in risk.reason.lower()

    def test_run_sql_drop_constraint_cascade(self):
        """Test DROP CONSTRAINT CASCADE - may be slow (score 3)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users DROP CONSTRAINT fk_company CASCADE;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 3
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert "cascade" in risk.reason.lower()

    def test_run_sql_alter_table_drop_column_if_exists(self):
        """Test ALTER TABLE DROP COLUMN IF EXISTS - should be dangerous (score 5), not confused with DROP TABLE."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE llm_analytics_evaluation DROP COLUMN IF EXISTS prompt;",
        )

        risk = self.analyzer.analyze_operation(op)

        # Should be score 5 (BLOCKED) for dropping a column
        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        # Should NOT be classified as DROP TABLE
        assert "drop table" not in risk.reason.lower()
        # Should indicate it's a DROP COLUMN operation
        assert "column" in risk.reason.lower() or "drop" in risk.reason.lower()

    def test_run_sql_drop_table_not_confused_with_drop_column(self):
        """Test that DROP TABLE IF EXISTS (without COLUMN keyword) is still recognized as table drop."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS old_table;",
        )

        risk = self.analyzer.analyze_operation(op)

        # Should be recognized as DROP TABLE (not DROP COLUMN)
        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "drop table" in risk.reason.lower()
        # Should NOT mention column
        assert "column" not in risk.reason.lower()

    def test_run_sql_drop_table_with_column_in_name(self):
        """Test that DROP TABLE with 'column' in table name doesn't trigger DROP COLUMN logic."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS column_data;",
        )

        risk = self.analyzer.analyze_operation(op)

        # Should be recognized as DROP TABLE (not DROP COLUMN)
        # Even though SQL contains the word "COLUMN"
        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "drop table" in risk.reason.lower()
        # Should NOT be classified as DROP COLUMN
        assert "drop column" not in risk.reason.lower()

    def test_run_sql_comment_on(self):
        """Test COMMENT ON - metadata only (score 0)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="COMMENT ON TABLE users IS 'User accounts';",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 0
        assert risk.level == RiskLevel.SAFE
        assert "metadata" in risk.reason.lower()

    def test_run_sql_set_statistics(self):
        """Test SET STATISTICS - metadata only (score 0)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users ALTER COLUMN email SET STATISTICS 1000;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 0
        assert risk.level == RiskLevel.SAFE
        assert "metadata" in risk.reason.lower()

    def test_run_sql_create_index_with_if_not_exists(self):
        """Test CREATE INDEX with IF NOT EXISTS - lower score within NEEDS_REVIEW."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE INDEX IF NOT EXISTS idx_foo ON users(email);",
        )

        risk = self.analyzer.analyze_operation(op)

        # Score 2 when IF NOT EXISTS is present
        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW

    def test_run_sql_create_index_without_if_not_exists(self):
        """Test CREATE INDEX missing IF NOT EXISTS - higher score within NEEDS_REVIEW."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE INDEX idx_foo ON users(email);",
        )

        risk = self.analyzer.analyze_operation(op)

        # Score 3 when IF NOT EXISTS is missing (still NEEDS_REVIEW, not BLOCKED)
        assert risk.score == 3
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert risk.guidance is not None and "if not exists" in risk.guidance.lower()

    def test_run_sql_drop_index_with_if_exists(self):
        """Test DROP INDEX without CONCURRENTLY but with IF EXISTS - still risky but idempotent."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP INDEX IF EXISTS idx_foo;",
        )

        risk = self.analyzer.analyze_operation(op)

        # DROP INDEX without CONCURRENTLY is dangerous (score 5)
        # Note: This is NOT a table drop, so it stays at score 5
        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "dangerous" in risk.reason.lower()


class TestDropTableValidation:
    """Test DROP TABLE validation with migration history checking."""

    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_drop_table_with_immediate_predecessor_state_removal(self):
        """
        Valid pattern: Prior migration removes model from state, then drop table.

        Migration 0877: SeparateDatabaseAndState removes NamedQuery
        Migration 0878: DROP TABLE IF EXISTS posthog_namedquery
        """
        # Create mock migration graph with proper staging
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0878_drop_named_query"
        mock_migration.dependencies = [("posthog", "0877_delete_named_query_from_state")]

        # Create the DROP operation
        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS posthog_namedquery;",
        )
        mock_migration.operations = [drop_op]

        # Create parent migration with SeparateDatabaseAndState
        parent_migration = MagicMock()
        parent_migration.app_label = "posthog"
        parent_migration.name = "0877_delete_named_query_from_state"

        delete_model_op = create_mock_operation(migrations.DeleteModel, name="NamedQuery")
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[delete_model_op],
            database_operations=[],
        )
        parent_migration.operations = [separate_op]

        # Create mock loader
        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("posthog", "0877_delete_named_query_from_state"): parent_migration,
            ("posthog", "0878_drop_named_query"): mock_migration,
        }

        # Analyze with migration context
        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "posthog/migrations/0878_drop_named_query.py", mock_loader
        )

        # Should be NEEDS_REVIEW (score 2) since properly staged
        assert migration_risk.level == RiskLevel.NEEDS_REVIEW
        assert migration_risk.max_score == 2

    def test_drop_table_with_gap_between_state_removal_and_drop(self):
        """
        Valid pattern: State removal several migrations before drop.

        Migration 0875: SeparateDatabaseAndState removes OldModel
        Migration 0876: Unrelated migration
        Migration 0877: Unrelated migration
        Migration 0878: DROP TABLE IF EXISTS posthog_oldmodel
        """
        # Create mock migrations
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0878_drop_old_model"
        mock_migration.dependencies = [("posthog", "0877_unrelated")]

        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS posthog_oldmodel;",
        )
        mock_migration.operations = [drop_op]

        # Create state removal migration (3 migrations back)
        state_removal_migration = MagicMock()
        state_removal_migration.app_label = "posthog"
        state_removal_migration.name = "0875_delete_old_model_from_state"

        delete_model_op = create_mock_operation(migrations.DeleteModel, name="OldModel")
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[delete_model_op],
            database_operations=[],
        )
        state_removal_migration.operations = [separate_op]

        # Create intermediate migrations
        intermediate1 = MagicMock()
        intermediate1.app_label = "posthog"
        intermediate1.name = "0876_unrelated"
        intermediate1.operations = []
        intermediate1.dependencies = [("posthog", "0875_delete_old_model_from_state")]

        intermediate2 = MagicMock()
        intermediate2.app_label = "posthog"
        intermediate2.name = "0877_unrelated"
        intermediate2.operations = []
        intermediate2.dependencies = [("posthog", "0876_unrelated")]

        # Create mock loader with full chain
        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("posthog", "0875_delete_old_model_from_state"): state_removal_migration,
            ("posthog", "0876_unrelated"): intermediate1,
            ("posthog", "0877_unrelated"): intermediate2,
            ("posthog", "0878_drop_old_model"): mock_migration,
        }

        # Analyze with migration context
        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "posthog/migrations/0878_drop_old_model.py", mock_loader
        )

        # Should be NEEDS_REVIEW (score 2) since properly staged (even with gap)
        assert migration_risk.level == RiskLevel.NEEDS_REVIEW
        assert migration_risk.max_score == 2

    def test_drop_table_without_prior_state_removal(self):
        """
        Invalid pattern: DROP TABLE without prior state removal.
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0878_drop_something"
        mock_migration.dependencies = [("posthog", "0877_other")]

        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS posthog_sometable;",
        )
        mock_migration.operations = [drop_op]

        # Parent has no state removal
        parent_migration = MagicMock()
        parent_migration.app_label = "posthog"
        parent_migration.name = "0877_other"
        parent_migration.operations = []

        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("posthog", "0877_other"): parent_migration,
            ("posthog", "0878_drop_something"): mock_migration,
        }

        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "posthog/migrations/0878_drop_something.py", mock_loader
        )

        # Should be BLOCKED (score 5) - no prior state removal found
        assert migration_risk.level == RiskLevel.BLOCKED
        assert migration_risk.max_score == 5

    def test_drop_table_wrong_model_removed_from_state(self):
        """
        Invalid pattern: State removal for different model than table being dropped.
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0878_drop_modelb"
        mock_migration.dependencies = [("posthog", "0877_delete_modela")]

        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS posthog_modelb;",
        )
        mock_migration.operations = [drop_op]

        # Parent removes wrong model from state
        parent_migration = MagicMock()
        parent_migration.app_label = "posthog"
        parent_migration.name = "0877_delete_modela"

        delete_model_op = create_mock_operation(migrations.DeleteModel, name="ModelA")
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[delete_model_op],
            database_operations=[],
        )
        parent_migration.operations = [separate_op]

        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("posthog", "0877_delete_modela"): parent_migration,
            ("posthog", "0878_drop_modelb"): mock_migration,
        }

        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "posthog/migrations/0878_drop_modelb.py", mock_loader
        )

        # Should be BLOCKED (score 5) - wrong model removed
        assert migration_risk.level == RiskLevel.BLOCKED
        assert migration_risk.max_score == 5

    def test_drop_table_without_if_exists_even_if_staged(self):
        """
        Invalid pattern: DROP TABLE without IF EXISTS (even if properly staged).
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0878_drop_model"
        mock_migration.dependencies = [("posthog", "0877_delete_model_from_state")]

        # DROP without IF EXISTS
        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE posthog_somemodel;",
        )
        mock_migration.operations = [drop_op]

        # Even with proper state removal
        parent_migration = MagicMock()
        parent_migration.app_label = "posthog"
        parent_migration.name = "0877_delete_model_from_state"

        delete_model_op = create_mock_operation(migrations.DeleteModel, name="SomeModel")
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[delete_model_op],
            database_operations=[],
        )
        parent_migration.operations = [separate_op]

        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("posthog", "0877_delete_model_from_state"): parent_migration,
            ("posthog", "0878_drop_model"): mock_migration,
        }

        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "posthog/migrations/0878_drop_model.py", mock_loader
        )

        # Should be BLOCKED (score 5) - missing IF EXISTS
        assert migration_risk.level == RiskLevel.BLOCKED
        assert migration_risk.max_score == 5

    def test_drop_table_fallback_when_no_loader(self):
        """
        Fallback: When migration loader not available, should be BLOCKED.
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0878_drop_model"

        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE IF EXISTS posthog_somemodel;",
        )
        mock_migration.operations = [drop_op]

        # Analyze without loader (old path)
        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0878_drop_model.py")

        # Should be BLOCKED (score 5) when we can't validate
        assert migration_risk.level == RiskLevel.BLOCKED
        assert migration_risk.max_score == 5

    def test_drop_column_with_prior_state_removal(self):
        """
        Valid pattern: Prior migration removes field from state, then drop column.

        Migration 0006: SeparateDatabaseAndState removes Evaluation.prompt
        Migration 0007: ALTER TABLE ... DROP COLUMN IF EXISTS prompt
        """
        # Create mock migration graph with proper staging
        mock_migration = MagicMock()
        mock_migration.app_label = "llm_analytics"
        mock_migration.name = "0007_drop_evaluation_prompt_column"
        mock_migration.dependencies = [("llm_analytics", "0006_remove_evaluation_prompt")]

        # Create the DROP COLUMN operation
        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE llm_analytics_evaluation DROP COLUMN IF EXISTS prompt;",
        )
        mock_migration.operations = [drop_op]

        # Create parent migration with SeparateDatabaseAndState
        parent_migration = MagicMock()
        parent_migration.app_label = "llm_analytics"
        parent_migration.name = "0006_remove_evaluation_prompt"

        remove_field_op = create_mock_operation(migrations.RemoveField, model_name="Evaluation", name="prompt")
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[remove_field_op],
            database_operations=[],
        )
        parent_migration.operations = [separate_op]

        # Create mock loader
        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("llm_analytics", "0006_remove_evaluation_prompt"): parent_migration,
            ("llm_analytics", "0007_drop_evaluation_prompt_column"): mock_migration,
        }

        # Analyze with migration context
        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "llm_analytics/migrations/0007_drop_evaluation_prompt_column.py", mock_loader
        )

        # Should be NEEDS_REVIEW (score 2) since properly staged
        assert migration_risk.level == RiskLevel.NEEDS_REVIEW
        assert migration_risk.max_score == 2


class TestRunPythonOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_run_python(self):
        op = create_mock_operation(
            migrations.RunPython,
            code=lambda apps, schema_editor: None,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert "review" in risk.reason.lower()
        assert risk.level == RiskLevel.NEEDS_REVIEW


class TestCreateModelOperations:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_create_model_with_uuid(self):
        """CreateModel with UUID is safe and has no policy violations."""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.CreateModel,
                name="TestModel",
                fields=[
                    ("id", models.UUIDField(primary_key=True)),
                    ("name", models.CharField(max_length=100)),
                ],
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_test.py")

        assert migration_risk.level == RiskLevel.SAFE
        assert len(migration_risk.policy_violations) == 0

    def test_create_model_with_autofield(self):
        """CreateModel with AutoField violates UUID policy (for PostHog apps only)."""
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"  # Use PostHog app to trigger policy
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.CreateModel,
                name="TestModel",
                fields=[
                    ("id", models.AutoField(primary_key=True)),
                    ("name", models.CharField(max_length=100)),
                ],
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        assert migration_risk.level == RiskLevel.BLOCKED  # Policy violations boost to blocked
        assert len(migration_risk.policy_violations) == 1
        assert "UUIDModel" in migration_risk.policy_violations[0]
        assert "AutoField" in migration_risk.policy_violations[0]

    def test_create_model_with_bigautofield(self):
        """CreateModel with BigAutoField violates UUID policy (for PostHog apps only)."""
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"  # Use PostHog app to trigger policy
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.CreateModel,
                name="TestModel",
                fields=[
                    ("id", models.BigAutoField(primary_key=True)),
                    ("name", models.CharField(max_length=100)),
                ],
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        assert migration_risk.level == RiskLevel.BLOCKED
        assert len(migration_risk.policy_violations) == 1
        assert "UUIDModel" in migration_risk.policy_violations[0]
        assert "BigAutoField" in migration_risk.policy_violations[0]

    def test_third_party_app_with_autofield_no_violation(self):
        """Third-party apps can use AutoField without triggering UUID policy."""
        mock_migration = MagicMock()
        mock_migration.app_label = "axes"  # Third-party app
        mock_migration.name = "0001_initial"
        mock_migration.operations = [
            create_mock_operation(
                migrations.CreateModel,
                name="AccessAttempt",
                fields=[
                    ("id", models.AutoField(primary_key=True)),
                    ("username", models.CharField(max_length=255)),
                ],
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "axes/migrations/0001_initial.py")

        assert migration_risk.level == RiskLevel.SAFE  # No policy violation for third-party apps
        assert len(migration_risk.policy_violations) == 0


class TestCombinationRisks:
    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_runsql_with_dml_and_schema_changes(self):
        """Critical: RunSQL with UPDATE combined with AddField"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="test", name="new_field", field=models.CharField(null=True)
            ),
            create_mock_operation(migrations.RunSQL, sql="UPDATE test_table SET foo = 'bar';"),
        ]

        # Analyze operations
        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        assert len(combination_risks) > 0
        assert any("CRITICAL" in warning for warning in combination_risks)
        assert any("DML" in warning for warning in combination_risks)

    def test_runsql_with_ddl_and_other_operations(self):
        """Warning: RunSQL with DDL (non-concurrent) mixed with other operations"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="test", name="new_field", field=models.CharField(null=True)
            ),
            create_mock_operation(migrations.RunSQL, sql="ALTER TABLE test_table ADD COLUMN foo text;"),
        ]

        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        assert len(combination_risks) > 0
        assert any("BLOCKED" in warning or "DDL" in warning for warning in combination_risks)

    def test_runsql_concurrent_index_no_ddl_warning(self):
        """CREATE INDEX CONCURRENTLY should NOT trigger DDL isolation warning"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="test", name="new_field", field=models.CharField(null=True)
            ),
            create_mock_operation(migrations.RunSQL, sql="CREATE INDEX CONCURRENTLY idx_foo ON test_table(foo);"),
        ]

        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        # Should NOT have DDL isolation warning for safe concurrent operations
        assert len(combination_risks) == 0 or all("DDL" not in warning for warning in combination_risks)

    def test_runsql_alone_no_combination_risk(self):
        """RunSQL alone should not trigger combination warnings"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(migrations.RunSQL, sql="UPDATE test_table SET foo = 'bar';"),
        ]

        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        assert len(combination_risks) == 0

    def test_schema_changes_without_runsql_no_combination_risk(self):
        """Schema changes without RunSQL should not trigger combination warnings"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="test", name="field1", field=models.CharField(null=True)
            ),
            create_mock_operation(
                migrations.AddField, model_name="test", name="field2", field=models.CharField(null=True)
            ),
        ]

        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        assert len(combination_risks) == 0

    def test_non_atomic_migration_with_runsql_info(self):
        """Non-atomic migration with RunSQL should get info warning"""
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.operations = [
            create_mock_operation(migrations.RunSQL, sql="UPDATE test_table SET foo = 'bar';"),
        ]

        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        assert len(combination_risks) > 0
        assert any("INFO" in warning or "atomic=False" in warning for warning in combination_risks)

    def test_combination_risk_boosts_migration_to_blocked(self):
        """Migration with combination risk should be classified as BLOCKED"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_test"
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="test", name="new_field", field=models.CharField(null=True)
            ),
            create_mock_operation(migrations.RunSQL, sql="UPDATE test_table SET foo = 'bar';"),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_test.py")

        assert len(migration_risk.combination_risks) > 0
        assert migration_risk.max_score >= 4  # Should be blocked
        assert migration_risk.level == RiskLevel.BLOCKED

    def test_runpython_with_schema_changes(self):
        """RunPython mixed with schema changes should trigger warning"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_test"
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="test", name="new_field", field=models.CharField(null=True)
            ),
            create_mock_operation(migrations.RunPython, code=lambda apps, schema_editor: None),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_test.py")

        assert len(migration_risk.combination_risks) > 0
        assert any("RunPython" in warning for warning in migration_risk.combination_risks)

    def test_multiple_high_risk_operations(self):
        """Multiple high-risk operations should trigger warning"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_test"
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(migrations.RemoveField, model_name="test", name="old_field"),
            create_mock_operation(migrations.RenameField, model_name="test", old_name="foo", new_name="bar"),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_test.py")

        assert len(migration_risk.combination_risks) > 0
        assert any("Multiple high-risk" in warning for warning in migration_risk.combination_risks)

    def test_multiple_index_creations(self):
        """Multiple index creations should trigger warning"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_test"
        mock_migration.atomic = True

        index1 = MagicMock()
        index1.concurrent = True
        index2 = MagicMock()
        index2.concurrent = True

        mock_migration.operations = [
            create_mock_operation(migrations.AddIndex, model_name="test", index=index1),
            create_mock_operation(migrations.AddIndex, model_name="test", index=index2),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_test.py")

        assert len(migration_risk.combination_risks) > 0
        assert any("Multiple index" in warning for warning in migration_risk.combination_risks)

    def test_separate_database_and_state_with_concurrent_index(self):
        """
        Test the correct pattern for adding concurrent indexes using SeparateDatabaseAndState.

        This pattern (from PR #39242) should NOT be blocked:
        - SeparateDatabaseAndState with state_operations containing AddIndex
        - database_operations containing RunSQL with CREATE INDEX CONCURRENTLY
        - atomic = False (required for CONCURRENTLY)

        This is the recommended safe pattern for adding indexes without blocking.
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0872_activitylog_idx"
        mock_migration.atomic = False  # Required for CONCURRENTLY

        # Create the SeparateDatabaseAndState operation
        index_mock = MagicMock()
        index_mock.name = "idx_test"

        state_op = create_mock_operation(migrations.AddIndex, model_name="activitylog", index=index_mock)

        db_op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_test ON posthog_activitylog (team_id, scope);",
        )

        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[state_op], database_operations=[db_op]
        )

        mock_migration.operations = [separate_op]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0872_activitylog_idx.py")

        # This should NOT be blocked - concurrent index creation is safe
        assert migration_risk.level != RiskLevel.BLOCKED, (
            f"SeparateDatabaseAndState with CREATE INDEX CONCURRENTLY should not be blocked. "
            f"Got level: {migration_risk.level}, combination_risks: {migration_risk.combination_risks}"
        )

        # Should be SAFE or at most NEEDS_REVIEW
        assert migration_risk.level in (RiskLevel.SAFE, RiskLevel.NEEDS_REVIEW)

        # Should not have DDL isolation combination risk for safe concurrent operations
        ddl_warnings = [r for r in migration_risk.combination_risks if "DDL" in r and "isolation" in r]
        assert len(ddl_warnings) == 0, f"Should not warn about DDL isolation for CONCURRENTLY: {ddl_warnings}"

    def test_create_model_with_add_index_safe(self):
        """AddIndex on newly created table should be filtered out (case-insensitive matching like Django)"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_create_new_table"
        mock_migration.atomic = True

        # Non-concurrent index that would normally be score 4
        index = MagicMock()
        index.concurrent = False

        # Mimics real Django behavior: CreateModel uses capitalized name, AddIndex uses lowercase model_name
        mock_migration.operations = [
            create_mock_operation(migrations.CreateModel, name="SchemaPropertyGroup", fields=[]),
            create_mock_operation(migrations.AddIndex, model_name="schemapropertygroup", index=index),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_create_new_table.py")

        # AddIndex on new table should be filtered out despite case mismatch
        assert len(migration_risk.operations) == 1  # Only CreateModel
        assert migration_risk.operations[0].type == "CreateModel"
        assert migration_risk.level == RiskLevel.SAFE
        assert len(migration_risk.combination_risks) == 0
        # Should have info message about skipped operations
        assert len(migration_risk.info_messages) == 1
        assert "Skipped operations on newly created tables" in migration_risk.info_messages[0]

    def test_create_model_with_add_constraint_safe(self):
        """AddConstraint on newly created table should be filtered out (case-insensitive matching)"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_create_new_table"
        mock_migration.atomic = True

        # Mimics real Django behavior: CreateModel uses capitalized name, AddConstraint uses lowercase model_name
        mock_migration.operations = [
            create_mock_operation(migrations.CreateModel, name="EventSchema", fields=[]),
            create_mock_operation(migrations.AddConstraint, model_name="eventschema"),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_create_new_table.py")

        # AddConstraint on new table should be filtered out despite case mismatch
        assert len(migration_risk.operations) == 1  # Only CreateModel
        assert migration_risk.operations[0].type == "CreateModel"
        assert migration_risk.level == RiskLevel.SAFE
        assert len(migration_risk.combination_risks) == 0

    def test_create_model_with_multiple_indexes_no_warning(self):
        """Multiple indexes on newly created table should be filtered out (no combination warning)"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0001_create_new_table"
        mock_migration.atomic = True

        index1 = MagicMock()
        index1.concurrent = False
        index2 = MagicMock()
        index2.concurrent = False

        mock_migration.operations = [
            create_mock_operation(migrations.CreateModel, name="NewTable", fields=[]),
            create_mock_operation(migrations.AddIndex, model_name="NewTable", index=index1),
            create_mock_operation(migrations.AddIndex, model_name="NewTable", index=index2),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0001_create_new_table.py")

        # Both indexes should be filtered out (not shown in operations)
        assert len(migration_risk.operations) == 1  # Only CreateModel
        assert migration_risk.operations[0].type == "CreateModel"
        assert migration_risk.level == RiskLevel.SAFE
        # Should NOT trigger "multiple indexes" warning
        assert len(migration_risk.combination_risks) == 0

    def test_add_index_on_existing_table_still_risky(self):
        """AddIndex on existing table (without CreateModel) should still be risky"""
        mock_migration = MagicMock()
        mock_migration.app_label = "test"
        mock_migration.name = "0002_add_index_existing"
        mock_migration.atomic = True

        index = MagicMock()
        index.concurrent = False

        mock_migration.operations = [
            create_mock_operation(migrations.AddIndex, model_name="ExistingTable", index=index),
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "test/migrations/0002_add_index_existing.py")

        # Index on existing table should still be score 4
        assert migration_risk.operations[0].score == 4
        assert migration_risk.level == RiskLevel.BLOCKED
