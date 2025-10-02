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
        op = create_mock_operation(
            migrations.RenameModel,
            old_name="OldModel",
            new_name="NewModel",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 4
        assert risk.level == RiskLevel.BLOCKED


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

    def test_run_sql_with_drop(self):
        op = create_mock_operation(
            migrations.RunSQL,
            sql="DROP TABLE foo;",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 5
        assert "dangerous" in risk.reason.lower()
        assert risk.level == RiskLevel.BLOCKED

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

    def test_run_sql_with_concurrent_index(self):
        """Test CREATE INDEX CONCURRENTLY - should need review but not be high risk."""
        op = create_mock_operation(
            migrations.RunSQL,
            sql="CREATE INDEX CONCURRENTLY idx_foo ON users(foo);",
        )

        risk = self.analyzer.analyze_operation(op)

        assert risk.score == 2
        assert risk.level == RiskLevel.NEEDS_REVIEW


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
        """Warning: RunSQL with DDL mixed with other operations"""
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

        assert len(combination_risks) > 0
        assert any("WARNING" in warning or "DDL" in warning for warning in combination_risks)

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
