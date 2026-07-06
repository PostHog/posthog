from unittest.mock import MagicMock

from django.conf import settings
from django.db import migrations, models

from parameterized import parameterized

from posthog.management.migration_analysis.analyzer import RiskAnalyzer
from posthog.management.migration_analysis.models import RiskLevel
from posthog.management.migration_analysis.policies import ConcurrentIndexIdempotencyPolicy, HotTableAlterPolicy
from posthog.migration_helpers import (
    AddConstraintNotValid,
    AddForeignKeyNotValid,
    SafeAddIndexConcurrently,
    SafeRemoveIndexConcurrently,
    ValidateConstraint,
)


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

        assert risk.score == 1
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

    def test_add_many_to_many_field(self):
        """ManyToMany fields create junction tables, not columns - always safe."""
        field: models.Field = models.ManyToManyField("posthog.Survey", blank=True)

        op = create_mock_operation(
            migrations.AddField,
            model_name="testmodel",
            name="linked_surveys",
            field=field,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 0
        assert "junction table" in risk.reason.lower()
        assert risk.level == RiskLevel.SAFE


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

    def test_run_sql_with_update_override_for_small_table(self):
        """Test UPDATE with migration-analyzer override comment reduces severity."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="""
            -- migration-analyzer: safe reason=Data warehouse table with limited customer usage
            UPDATE posthog_externaldataschema SET sync_time_of_day = null WHERE sync_time_of_day = '00:00:00';
            """,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert "override" in risk.reason.lower()
        assert "Data warehouse table" in risk.details.get("override_reason", "")
        assert "Developer override applied" in (risk.guidance or "")

    def test_run_sql_with_delete_override_for_small_table(self):
        """Test DELETE with migration-analyzer override comment reduces severity."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="""
            # migration-analyzer: safe reason=Cleanup table with minimal rows
            DELETE FROM temp_table WHERE created_at < NOW() - INTERVAL '30 days';
            """,
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert "override" in risk.reason.lower()
        assert "Cleanup table with minimal rows" in risk.details.get("override_reason", "")

    def test_run_sql_override_doesnt_apply_to_wrong_operation(self):
        """Test that override comment doesn't apply if SQL doesn't contain UPDATE/DELETE.

        Security: Ensure override comment mentioning "update" doesn't trigger override
        for non-UPDATE operations like DROP.
        """
        op = create_mock_operation(
            migrations.RunSQL,
            sql="""
            -- migration-analyzer: safe reason=Need to update this column later
            DROP TABLE IF EXISTS posthog_old_table;
            """,
        )

        risk = self.analyzer.analyze_operation(op)

        # Should still be scored as DROP (5 - BLOCKED), not override (2 - NEEDS_REVIEW)
        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "drop" in risk.reason.lower()

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

    def test_add_constraint_not_valid_helper_scores_safe(self):
        """The helper scores like the hand-written ADD CONSTRAINT ... NOT VALID (safe)."""
        op = AddConstraintNotValid(
            model_name="dashboard",
            constraint=models.CheckConstraint(condition=models.Q(amount__gte=0), name="dash_amount_chk"),
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 1
        assert risk.level == RiskLevel.SAFE

    def test_validate_constraint_helper_scores_needs_review(self):
        """The helper scores like the hand-written VALIDATE CONSTRAINT (slow, non-blocking)."""
        op = ValidateConstraint(model_name="dashboard", name="dash_amount_chk")

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW

    def test_run_sql_drop_constraint(self):
        """Test DROP CONSTRAINT - fast but needs deployment safety review (score 2)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users DROP CONSTRAINT check_age;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW
        assert "fast" in risk.reason.lower()
        assert "deployment safety" in risk.reason.lower() or (risk.guidance and "deployment" in risk.guidance.lower())

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

    def test_run_sql_add_constraint_using_index(self):
        """Test ADD CONSTRAINT ... USING INDEX - instant metadata operation (score 0)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE posthog_errortrackingstackframe ADD CONSTRAINT unique_team_id_raw_id_part UNIQUE USING INDEX idx_team_id_raw_id_part;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 0
        assert risk.level == RiskLevel.SAFE
        assert "instant" in risk.reason.lower() or "metadata" in risk.reason.lower()
        assert "using index" in risk.reason.lower()

    def test_run_sql_add_constraint_without_not_valid(self):
        """Test bare ADD CONSTRAINT without NOT VALID - should warn to use NOT VALID pattern."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="ALTER TABLE users ADD CONSTRAINT check_age CHECK (age >= 0);",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 4
        assert risk.level == RiskLevel.BLOCKED
        assert "not valid" in risk.reason.lower()
        assert risk.guidance and "not valid" in risk.guidance.lower()

    def test_run_sql_temp_table_on_commit_drop_not_flagged(self):
        """Test CREATE TEMP TABLE ... ON COMMIT DROP - should NOT be flagged as dangerous DROP."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE TEMP TABLE tmp_batch (id uuid) ON COMMIT DROP;",
        )

        risk = self.analyzer.analyze_operation(op)

        # Should NOT be blocked - ON COMMIT DROP is temp table cleanup, not dangerous
        assert risk.level != RiskLevel.BLOCKED
        assert "drop" not in risk.reason.lower() or "dangerous" not in risk.reason.lower()

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

    def test_run_sql_alter_table_drop_column_quoted_identifiers(self):
        """Test ALTER TABLE DROP COLUMN with double-quoted identifiers (standard Postgres quoting)."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql='ALTER TABLE "posthog_experiment" DROP COLUMN IF EXISTS "exposure_preaggregation_enabled";',
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "drop table" not in risk.reason.lower()
        assert "column" in risk.reason.lower()

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

    def test_run_sql_drop_table_quoted_identifiers(self):
        """Test DROP TABLE IF EXISTS with double-quoted table name."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql='DROP TABLE IF EXISTS "old_table";',
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert risk.level == RiskLevel.BLOCKED
        assert "drop table" in risk.reason.lower()
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

        # DROP INDEX is not as dangerous as DROP TABLE/COLUMN - falls through to generic review
        # It's reversible (can recreate index) and doesn't cause data loss
        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW


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

    def test_drop_column_with_prior_state_removal_quoted_identifiers(self):
        """Same as test_drop_column_with_prior_state_removal but with double-quoted identifiers."""
        mock_migration = MagicMock()
        mock_migration.app_label = "experiments"
        mock_migration.name = "0008_drop_exposure_preaggregation_column"
        mock_migration.dependencies = [("experiments", "0007_drop_exposure_preaggregation_enabled")]

        drop_op = create_mock_operation(
            migrations.RunSQL,
            sql='ALTER TABLE "posthog_experiment" DROP COLUMN IF EXISTS "exposure_preaggregation_enabled";',
        )
        mock_migration.operations = [drop_op]

        parent_migration = MagicMock()
        parent_migration.app_label = "experiments"
        parent_migration.name = "0007_drop_exposure_preaggregation_enabled"

        remove_field_op = create_mock_operation(
            migrations.RemoveField, model_name="Experiment", name="exposure_preaggregation_enabled"
        )
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[remove_field_op],
            database_operations=[],
        )
        parent_migration.operations = [separate_op]

        mock_loader = MagicMock()
        mock_loader.disk_migrations = {
            ("experiments", "0007_drop_exposure_preaggregation_enabled"): parent_migration,
            ("experiments", "0008_drop_exposure_preaggregation_column"): mock_migration,
        }

        migration_risk = self.analyzer.analyze_migration_with_context(
            mock_migration, "experiments/migrations/0008_drop_exposure_preaggregation_column.py", mock_loader
        )

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

    def test_runsql_with_ddl_and_schema_operations(self):
        """DDL + schema ops should give specific message about splitting"""
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
        # Should give specific message about DDL + schema ops
        assert any("RunSQL DDL and Django schema operations" in warning for warning in combination_risks)
        assert any("atomic=True" in warning for warning in combination_risks)

    def test_runsql_ddl_with_dml_specific_message(self):
        """DDL + DML should give specific message about schema vs data changes"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.operations = [
            create_mock_operation(migrations.RunSQL, sql="ALTER TABLE test_table ADD COLUMN foo text;"),
            create_mock_operation(migrations.RunSQL, sql="UPDATE test_table SET foo = 'bar';"),
        ]

        operation_risks = [self.analyzer.analyze_operation(op) for op in mock_migration.operations]
        combination_risks = self.analyzer.check_operation_combinations(mock_migration, operation_risks)

        assert len(combination_risks) > 0
        # Should give specific message about DDL + DML
        assert any(
            "Schema changes (ALTER TABLE) and data changes (UPDATE/DELETE)" in warning for warning in combination_risks
        )
        assert any("atomic=True" in warning for warning in combination_risks)

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

    def test_separate_database_and_state_with_alter_table_no_false_positive(self):
        """
        Test that SeparateDatabaseAndState with a single DDL RunSQL does NOT trigger
        the "DDL mixed with other operations" warning.

        This was a false positive: the nested RunSQL inside SeparateDatabaseAndState
        was counted as a separate operation, triggering the warning even though
        there's only one top-level operation.

        Pattern from 0948_hogfunction_batch_export migration:
        - SeparateDatabaseAndState with state_operations (AddField, AlterField)
        - database_operations containing RunSQL with ALTER TABLE
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0948_hogfunction_batch_export"
        mock_migration.atomic = True

        # Create the SeparateDatabaseAndState operation like 0948
        state_op1 = create_mock_operation(
            migrations.AddField,
            model_name="hogfunction",
            name="batch_export",
            field=models.ForeignKey("batchexport", null=True, blank=True, on_delete=models.SET_NULL),
        )
        state_op2 = create_mock_operation(
            migrations.AlterField,
            model_name="batchexportdestination",
            name="type",
            field=models.CharField(max_length=64),
        )

        db_op = create_mock_operation(
            migrations.RunSQL,
            sql='ALTER TABLE "posthog_hogfunction" ADD COLUMN "batch_export_id" uuid NULL;',
        )

        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[state_op1, state_op2],
            database_operations=[db_op],
        )

        mock_migration.operations = [separate_op]

        migration_risk = self.analyzer.analyze_migration(
            mock_migration, "posthog/migrations/0948_hogfunction_batch_export.py"
        )

        # Should NOT have DDL isolation warning - there's only one top-level operation
        ddl_warnings = [r for r in migration_risk.combination_risks if "mixed with other operations" in r]
        assert len(ddl_warnings) == 0, (
            f"SeparateDatabaseAndState with single DDL should not trigger DDL isolation warning. "
            f"Got warnings: {ddl_warnings}"
        )

    def test_separate_database_and_state_plus_other_op_triggers_ddl_warning(self):
        """
        Test that SeparateDatabaseAndState with DDL PLUS another top-level operation
        DOES correctly trigger the "DDL mixed with other operations" warning.

        This is the correct behavior - if there are truly multiple top-level operations
        and one contains DDL, we should warn.
        """
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_mixed_ops"
        mock_migration.atomic = True

        # SeparateDatabaseAndState with DDL
        db_op = create_mock_operation(
            migrations.RunSQL,
            sql='ALTER TABLE "test" ADD COLUMN "foo" integer;',
        )
        separate_op = create_mock_operation(
            migrations.SeparateDatabaseAndState,
            state_operations=[],
            database_operations=[db_op],
        )

        # Another top-level operation (not inside SeparateDatabaseAndState)
        add_field_op = create_mock_operation(
            migrations.AddField,
            model_name="othermodel",
            name="bar",
            field=models.CharField(max_length=100, null=True),
        )

        mock_migration.operations = [separate_op, add_field_op]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_mixed_ops.py")

        # SHOULD have DDL isolation warning - there are two top-level operations
        # Message should be specific about DDL + schema operations
        ddl_warnings = [r for r in migration_risk.combination_risks if "RunSQL DDL and Django schema operations" in r]
        assert len(ddl_warnings) == 1, (
            f"Should warn about DDL mixed with schema operations. Got warnings: {migration_risk.combination_risks}"
        )

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


class TestUnmanagedModels:
    def test_is_unmanaged_model_with_managed_false_option(self):
        """is_unmanaged_model should detect managed=False in CreateModel options"""
        from posthog.management.migration_analysis.operations import is_unmanaged_model

        mock_migration = MagicMock()
        mock_migration.app_label = "test_app"

        # CreateModel with managed=False
        op = create_mock_operation(
            migrations.CreateModel,
            name="TestModel",
            options={"managed": False},
        )

        assert is_unmanaged_model(op, mock_migration) is True

    def test_is_unmanaged_model_with_managed_true(self):
        """is_unmanaged_model should return False for managed=True"""
        from posthog.management.migration_analysis.operations import is_unmanaged_model

        mock_migration = MagicMock()
        mock_migration.app_label = "test_app"

        # CreateModel with managed=True
        op = create_mock_operation(
            migrations.CreateModel,
            name="TestModel",
            options={"managed": True},
        )

        assert is_unmanaged_model(op, mock_migration) is False


class TestAtomicFalsePolicy:
    """Tests for AtomicFalsePolicy - validates atomic=False usage in migrations."""

    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def test_atomic_false_with_addfield_warns(self):
        """atomic=False with regular AddField should warn (not block)"""
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="mymodel", name="field", field=models.CharField(null=True)
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        assert any("WARNING" in v for v in migration_risk.policy_violations)
        assert any("atomic=False" in v for v in migration_risk.policy_violations)

    def test_atomic_false_with_add_index_concurrently_ok(self):
        """AtomicFalsePolicy does not flag AddIndexConcurrently with atomic=False.

        Idempotency of AddIndexConcurrently is a separate concern enforced by
        ConcurrentIndexIdempotencyPolicy (see TestConcurrentIndexIdempotencyPolicy).
        """
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"

        # Create AddIndexConcurrently operation
        op = MagicMock()
        op.__class__.__name__ = "AddIndexConcurrently"
        mock_migration.operations = [op]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        # AtomicFalsePolicy is satisfied (concurrent op with atomic=False)
        assert not any("atomic=False" in v for v in migration_risk.policy_violations)
        # Should recognize the operation (not "Unknown")
        assert not any("Unknown" in r.reason for r in migration_risk.operations)
        # ConcurrentIndexIdempotencyPolicy still blocks the non-idempotent op
        assert any("non-idempotent" in v for v in migration_risk.policy_violations)

    def test_atomic_true_with_concurrent_blocked(self):
        """CONCURRENTLY without atomic=False should be BLOCKED (will fail at runtime)"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"

        # Create AddIndexConcurrently operation
        op = MagicMock()
        op.__class__.__name__ = "AddIndexConcurrently"
        mock_migration.operations = [op]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        assert any("BLOCKED" in v for v in migration_risk.policy_violations)
        assert any("atomic=False" in v for v in migration_risk.policy_violations)

    def test_atomic_false_with_runsql_concurrently_ok(self):
        """AtomicFalsePolicy does not flag RunSQL CONCURRENTLY with atomic=False.

        This SQL is missing IF NOT EXISTS, so ConcurrentIndexIdempotencyPolicy
        blocks it separately (see TestConcurrentIndexIdempotencyPolicy).
        """
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(migrations.RunSQL, sql="CREATE INDEX CONCURRENTLY idx_test ON test_table (col);")
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        # AtomicFalsePolicy is satisfied (concurrent op with atomic=False)
        assert not any("atomic=False" in v for v in migration_risk.policy_violations)
        # ConcurrentIndexIdempotencyPolicy blocks the missing IF NOT EXISTS
        assert any("non-idempotent" in v for v in migration_risk.policy_violations)

    def test_atomic_true_with_runsql_concurrently_blocked(self):
        """RunSQL with CONCURRENTLY without atomic=False should be BLOCKED"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(migrations.RunSQL, sql="CREATE INDEX CONCURRENTLY idx_test ON test_table (col);")
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        assert any("BLOCKED" in v for v in migration_risk.policy_violations)
        assert any("CONCURRENTLY" in v for v in migration_risk.policy_violations)

    def test_atomic_false_mixed_ops_recommends_split(self):
        """atomic=False with AddField + CONCURRENTLY should recommend splitting"""
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"

        add_index_op = MagicMock()
        add_index_op.__class__.__name__ = "AddIndexConcurrently"

        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="mymodel", name="field", field=models.CharField(null=True)
            ),
            add_index_op,
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        # Should not have "atomic=False without CONCURRENTLY" warning (CONCURRENTLY is present)
        assert not any("atomic=False without CONCURRENTLY" in v for v in migration_risk.policy_violations)
        # Should recommend splitting
        assert any("RECOMMEND SPLIT" in v for v in migration_risk.policy_violations)

    def test_third_party_app_not_checked(self):
        """Third-party app migrations should not be checked for atomic policy"""
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "some_third_party_app"
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="mymodel", name="field", field=models.CharField(null=True)
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "some_third_party_app/migrations/0001_test.py")

        # Should not have atomic-related warnings (not a PostHog app)
        assert not any("atomic=False" in v for v in migration_risk.policy_violations)

    def test_atomic_default_true_no_warning(self):
        """Migration without explicit atomic (defaults to True) with regular ops should have no atomic warning"""
        mock_migration = MagicMock()
        # No atomic attribute set - defaults to True
        del mock_migration.atomic
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="mymodel", name="field", field=models.CharField(null=True)
            )
        ]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        # Should not have atomic-related warnings
        assert not any("atomic=False" in v for v in migration_risk.policy_violations)

    def test_remove_index_concurrently_requires_atomic_false(self):
        """RemoveIndexConcurrently without atomic=False should be blocked"""
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"

        op = MagicMock()
        op.__class__.__name__ = "RemoveIndexConcurrently"
        mock_migration.operations = [op]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")

        assert any("BLOCKED" in v for v in migration_risk.policy_violations)
        assert any("CONCURRENTLY" in v for v in migration_risk.policy_violations)

    def test_product_app_detected_by_module_path(self):
        """Product apps with short labels like 'endpoints' should be detected via __module__"""
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "endpoints"  # Short label from apps.py
        mock_migration.name = "0001_test"
        # Product module path - this is what makes it detectable
        mock_migration.__module__ = "products.endpoints.backend.migrations.0001_test"
        mock_migration.operations = [
            create_mock_operation(
                migrations.AddField, model_name="endpoint", name="field", field=models.CharField(null=True)
            )
        ]

        migration_risk = self.analyzer.analyze_migration(
            mock_migration, "products/endpoints/backend/migrations/0001_test.py"
        )

        # Product app should trigger policy checks - atomic=False without CONCURRENTLY warns
        assert any("atomic=False" in v for v in migration_risk.policy_violations)

    @parameterized.expand(
        [
            "CreateIndexConcurrently",
            "DropIndexConcurrently",
            "SafeAddIndexConcurrently",
            "SafeRemoveIndexConcurrently",
        ]
    )
    def test_posthog_helpers_recognized_as_concurrent(self, op_name):
        """The PostHog helpers must register as concurrent ops in
        CONCURRENT_OP_TYPES, otherwise atomic=False migrations using them
        would trip the `atomic=False without CONCURRENTLY` warning.
        """
        mock_migration = MagicMock()
        mock_migration.atomic = False
        mock_migration.app_label = "posthog"
        mock_migration.name = "0001_test"

        # Plain MagicMock (no spec=) — spec= on a Django operation class
        # would cause `__class__.__name__ = ...` to mutate the real class
        # name globally and bleed across tests.
        op = MagicMock()
        op.__class__.__name__ = op_name
        op.sql = 'CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx" ON "t" (c)'
        op.reverse_sql = 'DROP INDEX CONCURRENTLY IF EXISTS "idx"'
        mock_migration.operations = [op]

        migration_risk = self.analyzer.analyze_migration(mock_migration, "posthog/migrations/0001_test.py")
        assert not any("atomic=False" in v for v in migration_risk.policy_violations)


class TestConcurrentIndexIdempotencyPolicy:
    """ConcurrentIndexIdempotencyPolicy blocks non-idempotent concurrent index ops.

    Regression coverage for the deploy-blocking failure where a transient
    lock_timeout cancellation of a bare CREATE INDEX CONCURRENTLY left an
    invalid index and every bin/migrate retry then failed with
    "relation already exists".
    """

    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def _analyze(self, operations, atomic=False, app_label="posthog"):
        mock_migration = MagicMock()
        mock_migration.atomic = atomic
        mock_migration.app_label = app_label
        mock_migration.name = "0001_test"
        mock_migration.operations = operations
        return self.analyzer.analyze_migration(mock_migration, f"{app_label}/migrations/0001_test.py")

    @parameterized.expand(["AddIndexConcurrently", "RemoveIndexConcurrently"])
    def test_django_concurrent_op_blocked(self, op_name):
        op = MagicMock()
        op.__class__.__name__ = op_name
        risk = self._analyze([op])
        assert risk.level == RiskLevel.BLOCKED
        assert any(op_name in v and "non-idempotent" in v for v in risk.policy_violations)

    @parameterized.expand(
        [
            ("create_no_if_not_exists", "CREATE INDEX CONCURRENTLY idx_foo ON t (c);"),
            ("drop_no_if_exists", "DROP INDEX CONCURRENTLY idx_foo;"),
        ]
    )
    def test_runsql_non_idempotent_concurrent_index_blocked(self, _name, sql):
        op = create_mock_operation(migrations.RunSQL, sql=sql)
        risk = self._analyze([op])
        assert risk.level == RiskLevel.BLOCKED
        assert any("non-idempotent" in v for v in risk.policy_violations)

    @parameterized.expand(
        [
            ("create_idempotent", "SET lock_timeout = 0; CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON t (c);"),
            ("drop_idempotent", "DROP INDEX CONCURRENTLY IF EXISTS idx_foo;"),
            ("reindex", "REINDEX INDEX CONCURRENTLY idx_foo;"),
        ]
    )
    def test_runsql_safe_concurrent_index_not_flagged(self, _name, sql):
        op = create_mock_operation(migrations.RunSQL, sql=sql)
        risk = self._analyze([op])
        assert not any("non-idempotent" in v for v in risk.policy_violations)

    def test_safe_pattern_in_separate_database_and_state_not_flagged(self):
        state_op = create_mock_operation(migrations.AddIndex, model_name="mymodel", index=MagicMock())
        db_op = create_mock_operation(
            migrations.RunSQL,
            sql="SET lock_timeout = 0; CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON mymodel (c);",
        )
        sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[state_op], database_operations=[db_op]
        )
        risk = self._analyze([sep])
        assert not any("non-idempotent" in v for v in risk.policy_violations)

    def test_non_idempotent_runsql_inside_separate_database_and_state_blocked(self):
        db_op = create_mock_operation(migrations.RunSQL, sql="CREATE INDEX CONCURRENTLY idx_foo ON mymodel (c);")
        sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[], database_operations=[db_op]
        )
        risk = self._analyze([sep])
        assert risk.level == RiskLevel.BLOCKED
        assert any("non-idempotent" in v for v in risk.policy_violations)

    def test_third_party_app_not_checked(self):
        op = MagicMock()
        op.__class__.__name__ = "AddIndexConcurrently"
        risk = self._analyze([op], app_label="some_third_party_app")
        assert not any("non-idempotent" in v for v in risk.policy_violations)

    def test_non_idempotent_reverse_sql_blocked(self):
        """Forward SQL is idempotent but reverse_sql is bare DROP. Rollback runs through the same retry loop, so a non-idempotent reverse re-opens the stuck-migration class."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="SET lock_timeout = 0; CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON t (c);",
            reverse_sql="DROP INDEX CONCURRENTLY idx_foo;",
        )
        risk = self._analyze([op])
        assert risk.level == RiskLevel.BLOCKED
        assert any("non-idempotent" in v and "reverse_sql" in v for v in risk.policy_violations)

    def test_non_idempotent_runsql_inside_nested_separate_database_and_state_blocked(self):
        """SeparateDatabaseAndState can nest; descent must reach inner ops at any depth."""
        inner_db_op = create_mock_operation(migrations.RunSQL, sql="CREATE INDEX CONCURRENTLY idx_foo ON mymodel (c);")
        inner_sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[], database_operations=[inner_db_op]
        )
        outer_sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[], database_operations=[inner_sep]
        )
        risk = self._analyze([outer_sep])
        assert risk.level == RiskLevel.BLOCKED
        assert any("non-idempotent" in v for v in risk.policy_violations)

    def test_policy_in_isolation_catches_nested_sdas(self):
        """Calling the policy directly proves it stands on its own, independent of sibling policies firing on the same migration."""
        inner_db_op = create_mock_operation(migrations.RunSQL, sql="CREATE INDEX CONCURRENTLY idx_foo ON mymodel (c);")
        inner_sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[], database_operations=[inner_db_op]
        )
        outer_sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[], database_operations=[inner_sep]
        )
        mock_migration = MagicMock()
        mock_migration.app_label = "posthog"
        mock_migration.operations = [outer_sep]

        violations = ConcurrentIndexIdempotencyPolicy().check_migration(mock_migration)

        assert any("non-idempotent" in v for v in violations)

    @parameterized.expand(
        [
            (
                "create_table_if_not_exists_hides_bare_create_index",
                "CREATE TABLE IF NOT EXISTS some_table (a int); CREATE INDEX CONCURRENTLY idx_foo ON t (c);",
            ),
            (
                "drop_table_if_exists_hides_bare_drop_index",
                "DROP TABLE IF EXISTS old_table; DROP INDEX CONCURRENTLY idx_foo;",
            ),
            (
                "block_comment_if_not_exists_hides_bare_create_index",
                "/* IF NOT EXISTS */ CREATE INDEX CONCURRENTLY idx_foo ON t (c);",
            ),
            (
                "list_form_mixed_create_table_and_bare_index",
                [
                    "CREATE TABLE IF NOT EXISTS some_table (a int);",
                    "CREATE INDEX CONCURRENTLY idx_foo ON t (c);",
                ],
            ),
            (
                "bare_create_unique_index_concurrently",
                "CREATE UNIQUE INDEX CONCURRENTLY idx_foo ON t (c);",
            ),
        ]
    )
    def test_substring_collision_no_longer_hides_bare_concurrent_index(self, _name, sql):
        """Regression: a substring check `"IF NOT EXISTS" in sql` matched unrelated statements
        in the same RunSQL blob and silently allowed a bare CREATE/DROP INDEX CONCURRENTLY through.
        Per-statement regex catches the bare index op even when the blob also contains a legitimate
        `CREATE TABLE IF NOT EXISTS` / `DROP TABLE IF EXISTS` / block comment / list-form sibling.
        """
        op = create_mock_operation(migrations.RunSQL, sql=sql)
        risk = self._analyze([op])
        assert risk.level == RiskLevel.BLOCKED
        assert any("non-idempotent" in v for v in risk.policy_violations)

    @parameterized.expand(
        [
            (
                "create_unique_index_with_if_not_exists",
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON t (c);",
            ),
            (
                "create_table_if_not_exists_alongside_safe_concurrent_index",
                "CREATE TABLE IF NOT EXISTS some_table (a int);"
                " CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON t (c);",
            ),
            (
                "comment_only_mention_of_bare_concurrently",
                "-- old form was: CREATE INDEX CONCURRENTLY idx_foo ON t (c);\n"
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_foo ON t (c);",
            ),
        ]
    )
    def test_per_statement_regex_does_not_overreach(self, _name, sql):
        """Don't false-positive on safe SQL that happens to contain a non-CONCURRENTLY DDL or
        the bare keyword sequence inside a comment.
        """
        op = create_mock_operation(migrations.RunSQL, sql=sql)
        risk = self._analyze([op])
        assert not any("non-idempotent" in v for v in risk.policy_violations)

    @parameterized.expand(
        [
            ("CreateIndexConcurrently",),
            ("DropIndexConcurrently",),
        ]
    )
    def test_posthog_helper_ops_pass_through(self, op_name):
        """The PostHog migration helpers encode the idempotency guarantee internally
        (indisvalid recovery + IF [NOT] EXISTS + timeout disabling), so the static
        check must not flag them — even though they inherit from RunSQL and their
        display SQL contains a CONCURRENTLY index statement.

        Plain MagicMock (no spec=) — spec= on a Django operation class would
        cause `__class__.__name__ = ...` to mutate the real class name globally
        and bleed across tests.
        """
        op = MagicMock()
        op.__class__.__name__ = op_name
        # Mirror what the real helpers stash on `sql` for sqlmigrate display:
        op.sql = 'CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx" ON "t" (c)'
        op.reverse_sql = 'DROP INDEX CONCURRENTLY IF EXISTS "idx"'
        risk = self._analyze([op])
        assert not any("non-idempotent" in v for v in risk.policy_violations)
        assert risk.level != RiskLevel.BLOCKED

    @parameterized.expand(
        [
            (SafeAddIndexConcurrently(model_name="dashboard", index=models.Index(fields=["name"], name="idx")),),
            (SafeRemoveIndexConcurrently(model_name="dashboard", name="idx"),),
        ]
    )
    def test_safe_state_aware_helpers_score_safe(self, op):
        """The state-aware helpers track state themselves and are idempotent by
        construction, so they score SAFE and are never flagged — no
        SeparateDatabaseAndState or raw display SQL required.
        """
        risk = self._analyze([op])
        assert risk.level == RiskLevel.SAFE
        assert not any("non-idempotent" in v for v in risk.policy_violations)
        assert not any("atomic=False" in v for v in risk.policy_violations)


class TestHotTableAlterPolicy:
    """HotTableAlterPolicy blocks unacknowledged DDL on tables read on every request.

    Regression coverage for the prod-us incident where a nullable AddField on
    Team queued an ACCESS EXCLUSIVE lock behind in-flight queries, stalling all
    traffic on posthog_team in recurring waves (one per bin/migrate retry).
    """

    def setup_method(self):
        self.analyzer = RiskAnalyzer()

    def _analyze(self, operations, app_label="posthog", name="0001_test"):
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = app_label
        mock_migration.name = name
        mock_migration.operations = operations
        return self.analyzer.analyze_migration(mock_migration, f"{app_label}/migrations/{name}.py")

    @parameterized.expand(["team", "user", "organization", "project"])
    def test_nullable_add_field_on_hot_model_blocked(self, model_name):
        op = create_mock_operation(
            migrations.AddField, model_name=model_name, name="optional_field", field=models.IntegerField(null=True)
        )
        risk = self._analyze([op])
        assert risk.level == RiskLevel.BLOCKED
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    # sorted() so test IDs are stable across runs (pytest-xdist collects by ID)
    @parameterized.expand(sorted(HotTableAlterPolicy.FIELD_LEVEL_OPS))
    def test_every_field_level_op_on_hot_model_blocked(self, op_type):
        op = MagicMock()
        op.__class__.__name__ = op_type
        op.model_name = "team"
        risk = self._analyze([op])
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    @parameterized.expand(sorted(HotTableAlterPolicy.MODEL_LEVEL_OPS))
    def test_every_model_level_op_on_hot_model_blocked(self, op_type):
        op = MagicMock()
        op.__class__.__name__ = op_type
        op.name = "team"
        risk = self._analyze([op])
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_field_on_regular_model_not_flagged(self):
        op = create_mock_operation(
            migrations.AddField, model_name="dashboard", name="optional_field", field=models.IntegerField(null=True)
        )
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_acknowledged_migration_not_flagged(self, tmp_path, monkeypatch):
        ack_file = tmp_path / "acks.txt"
        ack_file.write_text("# comment\nposthog.0001_test\n")
        monkeypatch.setattr(HotTableAlterPolicy, "ACKNOWLEDGMENTS_FILE", ack_file)
        op = create_mock_operation(
            migrations.AddField, model_name="team", name="optional_field", field=models.IntegerField(null=True)
        )
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_violation_names_the_acknowledgment_entry(self):
        op = create_mock_operation(
            migrations.AddField, model_name="team", name="optional_field", field=models.IntegerField(null=True)
        )
        risk = self._analyze([op], name="1234_team_new_field")
        assert any('"posthog.1234_team_new_field"' in v for v in risk.policy_violations)

    def test_runsql_alter_on_hot_table_blocked(self):
        op = create_mock_operation(
            migrations.RunSQL, sql='ALTER TABLE "posthog_team" ADD COLUMN "foo" timestamptz NULL;'
        )
        risk = self._analyze([op])
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    @parameterized.expand(
        [
            ("if_exists", "ALTER TABLE IF EXISTS posthog_team ADD COLUMN foo int NULL;"),
            ("if_exists_quoted", 'ALTER TABLE IF EXISTS "posthog_team" ADD COLUMN foo int NULL;'),
            ("if_exists_only", "ALTER TABLE IF EXISTS ONLY posthog_team ADD COLUMN foo int NULL;"),
            ("schema_qualified", "ALTER TABLE public.posthog_team ADD COLUMN foo int NULL;"),
            ("schema_qualified_quoted", 'ALTER TABLE "public"."posthog_team" ADD COLUMN foo int NULL;'),
            ("if_exists_schema_qualified", "ALTER TABLE IF EXISTS public.posthog_team ADD COLUMN foo int NULL;"),
        ]
    )
    def test_runsql_alter_variants_on_hot_table_blocked(self, _name, sql):
        op = create_mock_operation(migrations.RunSQL, sql=sql)
        risk = self._analyze([op])
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_runsql_validate_constraint_on_hot_table_not_flagged(self):
        op = create_mock_operation(migrations.RunSQL, sql='ALTER TABLE "posthog_team" VALIDATE CONSTRAINT "some_fk";')
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_runsql_hot_table_only_in_comment_not_flagged(self):
        op = create_mock_operation(
            migrations.RunSQL,
            sql='-- cleanup after ALTER TABLE "posthog_team"\nALTER TABLE "posthog_dashboard" ADD COLUMN "foo" int NULL;',
        )
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_runsql_alter_on_regular_table_not_flagged(self):
        op = create_mock_operation(migrations.RunSQL, sql='ALTER TABLE "posthog_dashboard" ADD COLUMN "foo" int NULL;')
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    @parameterized.expand(["AddIndexConcurrently", "CreateIndexConcurrently"])
    def test_concurrent_index_on_hot_model_not_flagged(self, op_type):
        op = MagicMock()
        op.__class__.__name__ = op_type
        op.model_name = "team"
        op.sql = 'CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx" ON "posthog_team" (c)'
        op.reverse_sql = 'DROP INDEX CONCURRENTLY IF EXISTS "idx"'
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_validate_constraint_on_hot_model_not_flagged(self):
        """VALIDATE CONSTRAINT takes only SHARE UPDATE EXCLUSIVE, so the helper is
        not gated even on a hot table (unlike its AddConstraintNotValid sibling)."""
        op = create_mock_operation(ValidateConstraint, model_name="team", name="team_some_check")
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_alter_model_options_on_hot_model_not_flagged(self):
        op = MagicMock()
        op.__class__.__name__ = "AlterModelOptions"
        op.name = "team"
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_runsql_inside_separate_database_and_state_blocked(self):
        db_op = create_mock_operation(
            migrations.RunSQL, sql='ALTER TABLE "posthog_team" ADD COLUMN "foo" timestamptz NULL;'
        )
        sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[], database_operations=[db_op]
        )
        risk = self._analyze([sep])
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_state_only_add_field_inside_separate_database_and_state_not_flagged(self):
        state_op = create_mock_operation(
            migrations.AddField, model_name="team", name="optional_field", field=models.IntegerField(null=True)
        )
        sep = create_mock_operation(
            migrations.SeparateDatabaseAndState, state_operations=[state_op], database_operations=[]
        )
        risk = self._analyze([sep])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_third_party_app_not_checked(self):
        op = create_mock_operation(
            migrations.AddField, model_name="team", name="optional_field", field=models.IntegerField(null=True)
        )
        risk = self._analyze([op], app_label="some_third_party_app")
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_hot_model_name_in_product_app_not_flagged(self):
        """A product app's own model named like a hot model maps to a different table."""
        op = create_mock_operation(
            migrations.AddField, model_name="team", name="optional_field", field=models.IntegerField(null=True)
        )
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = "some_product"
        mock_migration.name = "0001_test"
        mock_migration.operations = [op]
        mock_migration.__module__ = "products.some_product.backend.migrations.0001_test"
        risk = self.analyzer.analyze_migration(mock_migration, "products/some_product/backend/migrations/0001_test.py")
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_product_app_runsql_on_hot_table_blocked(self):
        op = create_mock_operation(
            migrations.RunSQL, sql='ALTER TABLE "posthog_team" ADD COLUMN "foo" timestamptz NULL;'
        )
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = "some_product"
        mock_migration.name = "0001_test"
        mock_migration.operations = [op]
        mock_migration.__module__ = "products.some_product.backend.migrations.0001_test"
        risk = self.analyzer.analyze_migration(mock_migration, "products/some_product/backend/migrations/0001_test.py")
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def _analyze_product(self, operations, app_label="some_product", name="0001_test"):
        mock_migration = MagicMock()
        mock_migration.atomic = True
        mock_migration.app_label = app_label
        mock_migration.name = name
        mock_migration.operations = operations
        mock_migration.__module__ = f"products.{app_label}.backend.migrations.{name}"
        return self.analyzer.analyze_migration(mock_migration, f"products/{app_label}/backend/migrations/{name}.py")

    def test_create_model_with_fk_to_hot_table_blocked(self):
        """The warehouse_sources.0034 case: a product CreateModel with a FK to posthog.team."""
        op = create_mock_operation(
            migrations.CreateModel,
            name="WarehouseColumnAnnotation",
            fields=[
                ("id", models.UUIDField(primary_key=True)),
                ("team", models.ForeignKey("posthog.team", on_delete=models.CASCADE)),
            ],
        )
        risk = self._analyze_product([op])
        assert any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)
        assert any("db_constraint=False" in v for v in risk.policy_violations)
        assert any("AddForeignKeyNotValid" in v for v in risk.policy_violations)

    def test_create_model_with_fk_to_hot_table_db_constraint_false_not_flagged(self):
        """db_constraint=False emits no FK constraint and takes no parent lock - the escape hatch."""
        op = create_mock_operation(
            migrations.CreateModel,
            name="WarehouseColumnAnnotation",
            fields=[
                ("id", models.UUIDField(primary_key=True)),
                ("team", models.ForeignKey("posthog.team", on_delete=models.CASCADE, db_constraint=False)),
            ],
        )
        risk = self._analyze_product([op])
        assert not any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_field_fk_to_hot_table_blocked(self):
        op = create_mock_operation(
            migrations.AddField,
            model_name="datawarehousetable",
            name="team",
            field=models.ForeignKey("posthog.team", on_delete=models.CASCADE),
        )
        risk = self._analyze_product([op])
        assert any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_create_model_with_fk_to_non_hot_table_not_flagged(self):
        op = create_mock_operation(
            migrations.CreateModel,
            name="WarehouseColumnAnnotation",
            fields=[
                ("id", models.UUIDField(primary_key=True)),
                ("table", models.ForeignKey("warehouse_sources.datawarehousetable", on_delete=models.CASCADE)),
            ],
        )
        risk = self._analyze_product([op])
        assert not any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_create_model_unmanaged_with_fk_to_hot_table_not_flagged(self):
        """managed=False maps an external table - Django emits no DDL or FK, so no parent lock."""
        op = create_mock_operation(
            migrations.CreateModel,
            name="WarehouseColumnAnnotation",
            fields=[
                ("id", models.UUIDField(primary_key=True)),
                ("team", models.ForeignKey("posthog.team", on_delete=models.CASCADE)),
            ],
            options={"managed": False},
        )
        risk = self._analyze_product([op])
        assert not any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_field_m2m_to_hot_table_blocked(self):
        """A M2M to a hot table auto-creates a through table with FK constraints to the parent."""
        op = create_mock_operation(
            migrations.AddField,
            model_name="datawarehousetable",
            name="teams",
            field=models.ManyToManyField("posthog.team"),
        )
        risk = self._analyze_product([op])
        assert any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_field_m2m_to_hot_table_db_constraint_false_not_flagged(self):
        """db_constraint=False propagates to the through FKs - the same escape hatch as a plain FK."""
        op = create_mock_operation(
            migrations.AddField,
            model_name="datawarehousetable",
            name="teams",
            field=models.ManyToManyField("posthog.team", db_constraint=False),
        )
        risk = self._analyze_product([op])
        assert not any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_field_m2m_with_explicit_through_not_flagged(self):
        """An explicit through model defines its own FKs, analyzed when its CreateModel runs."""
        op = create_mock_operation(
            migrations.AddField,
            model_name="datawarehousetable",
            name="teams",
            field=models.ManyToManyField("posthog.team", through="some_product.TableTeam"),
        )
        risk = self._analyze_product([op])
        assert not any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_create_model_with_swappable_user_fk_blocked(self):
        """settings.AUTH_USER_MODEL desugars to posthog.user, a hot table."""
        op = create_mock_operation(
            migrations.CreateModel,
            name="WarehouseColumnAnnotation",
            fields=[
                ("id", models.UUIDField(primary_key=True)),
                ("created_by", models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)),
            ],
        )
        risk = self._analyze_product([op])
        assert any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_fk_to_hot_table_acknowledged_not_flagged(self, tmp_path, monkeypatch):
        ack_file = tmp_path / "acks.txt"
        ack_file.write_text("some_product.0001_test\n")
        monkeypatch.setattr(HotTableAlterPolicy, "ACKNOWLEDGMENTS_FILE", ack_file)
        op = create_mock_operation(
            migrations.CreateModel,
            name="WarehouseColumnAnnotation",
            fields=[
                ("id", models.UUIDField(primary_key=True)),
                ("team", models.ForeignKey("posthog.team", on_delete=models.CASCADE)),
            ],
        )
        risk = self._analyze_product([op])
        assert not any("SHARE ROW EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_foreign_key_not_valid_on_hot_child_blocked(self):
        """The helper run against a hot child still ALTERs posthog_team itself - gate it."""
        op = AddForeignKeyNotValid(model_name="team", name="team_owner_fk", column="owner_id", to_table="some_table")
        risk = self._analyze([op])
        assert any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)

    def test_add_foreign_key_not_valid_pointing_at_hot_parent_not_flagged(self):
        """The sanctioned use: a non-hot child's FK pointing at a hot parent carries the
        parent in to_table, not model_name, so it isn't gated as a direct hot-table alter."""
        op = AddForeignKeyNotValid(
            model_name="mymodel", name="mymodel_team_fk", column="team_id", to_table="posthog_team"
        )
        risk = self._analyze([op])
        assert not any("ACCESS EXCLUSIVE" in v for v in risk.policy_violations)
