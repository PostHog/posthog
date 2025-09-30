# ruff: noqa: T201 allow print statements

import sys
from dataclasses import dataclass
from enum import Enum

from django.core.management.base import BaseCommand
from django.db import models

from posthog.management.commands.migration_utils import MigrationDiscovery


class RiskLevel(Enum):
    """Risk level definitions with scoring ranges"""

    SAFE = ("Safe", 0, 1, "\033[92m", "✅")
    NEEDS_REVIEW = ("Needs Review", 2, 3, "\033[93m", "⚠️")
    BLOCKED = ("Blocked", 4, 5, "\033[91m", "❌")

    def __init__(self, category: str, min_score: int, max_score: int, color: str, icon: str):
        self.category = category
        self.min_score = min_score
        self.max_score = max_score
        self.color = color
        self.icon = icon

    @classmethod
    def from_score(cls, score: int) -> "RiskLevel":
        """Determine risk level from a numeric score"""
        for level in cls:
            if level.min_score <= score <= level.max_score:
                return level
        return cls.BLOCKED if score > 3 else cls.SAFE


@dataclass
class OperationRisk:
    type: str
    score: int
    reason: str
    details: dict

    @property
    def level(self) -> RiskLevel:
        return RiskLevel.from_score(self.score)


@dataclass
class MigrationRisk:
    path: str
    app: str
    name: str
    operations: list[OperationRisk]
    combination_risks: list[str] = None  # List of combination warning messages

    def __post_init__(self):
        if self.combination_risks is None:
            self.combination_risks = []

    @property
    def max_score(self) -> int:
        # If there are combination risks, boost score to at least 4 (Blocked)
        base_score = max((op.score for op in self.operations), default=0)
        if self.combination_risks:
            return max(base_score, 4)
        return base_score

    @property
    def level(self) -> RiskLevel:
        return RiskLevel.from_score(self.max_score)

    @property
    def category(self) -> str:
        return self.level.category


class OperationAnalyzer:
    """Base class for operation-specific analyzers"""

    operation_type: str
    default_score: int = 2

    def analyze(self, op) -> OperationRisk:
        """Override in subclasses to provide specific analysis logic"""
        return OperationRisk(
            type=self.operation_type,
            score=self.default_score,
            reason=f"{self.operation_type} operation",
            details={},
        )


class AddFieldAnalyzer(OperationAnalyzer):
    operation_type = "AddField"

    def analyze(self, op) -> OperationRisk:
        field = op.field
        is_nullable = field.null or getattr(field, "blank", False)
        has_default = field.default != models.NOT_PROVIDED

        if not is_nullable and not has_default:
            return OperationRisk(
                type=self.operation_type,
                score=5,
                reason="Adding NOT NULL field without default locks table",
                details={"model": op.model_name, "field": op.name},
            )
        elif not is_nullable and has_default:
            return OperationRisk(
                type=self.operation_type,
                score=1,
                reason="Adding NOT NULL field with default (verify it's a constant)",
                details={"model": op.model_name, "field": op.name},
            )
        else:
            return OperationRisk(
                type=self.operation_type,
                score=0,
                reason="Adding nullable field is safe",
                details={"model": op.model_name, "field": op.name},
            )


class RemoveFieldAnalyzer(OperationAnalyzer):
    operation_type = "RemoveField"
    default_score = 5

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=5,
            reason="Dropping column breaks backwards compatibility and can't rollback",
            details={"model": op.model_name, "field": op.name},
        )


class DeleteModelAnalyzer(OperationAnalyzer):
    operation_type = "DeleteModel"
    default_score = 5

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=5,
            reason="Dropping table breaks backwards compatibility and can't rollback",
            details={"model": op.name},
        )


class AlterFieldAnalyzer(OperationAnalyzer):
    operation_type = "AlterField"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Field alteration may cause table locks or data loss",
            details={"model": op.model_name, "field": op.name},
        )


class RenameFieldAnalyzer(OperationAnalyzer):
    operation_type = "RenameField"
    default_score = 4

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Renaming column breaks old code during deployment",
            details={"model": op.model_name, "old": op.old_name, "new": op.new_name},
        )


class RenameModelAnalyzer(OperationAnalyzer):
    operation_type = "RenameModel"
    default_score = 4

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Renaming table breaks old code during deployment",
            details={"old": op.old_name, "new": op.new_name},
        )


class AlterModelTableAnalyzer(OperationAnalyzer):
    operation_type = "AlterModelTable"
    default_score = 4

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=4,
            reason="Changing table name breaks old code during deployment",
            details={},
        )


class AddIndexAnalyzer(OperationAnalyzer):
    operation_type = "AddIndex"
    default_score = 0

    def analyze(self, op) -> OperationRisk:
        if hasattr(op, "index"):
            concurrent = getattr(op.index, "concurrent", False)
            if not concurrent:
                return OperationRisk(
                    type=self.operation_type,
                    score=4,
                    reason="Non-concurrent index creation locks table",
                    details={},
                )
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Concurrent index is safe",
            details={},
        )


class AddConstraintAnalyzer(OperationAnalyzer):
    operation_type = "AddConstraint"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Adding constraint may lock table (use NOT VALID pattern)",
            details={},
        )


class RunSQLAnalyzer(OperationAnalyzer):
    operation_type = "RunSQL"
    default_score = 2

    def analyze(self, op) -> OperationRisk:
        sql = str(op.sql).upper()
        if "DROP" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=5,
                reason="RunSQL with DROP is dangerous",
                details={"sql": sql},
            )
        elif "UPDATE" in sql or "DELETE" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=4,
                reason="RunSQL with UPDATE/DELETE needs careful review for locking",
                details={"sql": sql},
            )
        elif "ALTER" in sql:
            return OperationRisk(
                type=self.operation_type,
                score=3,
                reason="RunSQL with ALTER may cause locks",
                details={"sql": sql},
            )
        else:
            return OperationRisk(
                type=self.operation_type,
                score=2,
                reason="RunSQL operation needs review",
                details={"sql": sql},
            )


class RunPythonAnalyzer(OperationAnalyzer):
    operation_type = "RunPython"
    default_score = 2

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=2,
            reason="RunPython data migration needs review for performance",
            details={},
        )


class CreateModelAnalyzer(OperationAnalyzer):
    operation_type = "CreateModel"
    default_score = 0

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=0,
            reason="Creating new table is safe",
            details={},
        )


class AlterUniqueTogetherAnalyzer(OperationAnalyzer):
    operation_type = "AlterUniqueTogether"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Altering unique constraints may lock table",
            details={},
        )


class AlterIndexTogetherAnalyzer(OperationAnalyzer):
    operation_type = "AlterIndexTogether"
    default_score = 3

    def analyze(self, op) -> OperationRisk:
        return OperationRisk(
            type=self.operation_type,
            score=3,
            reason="Altering indexes may lock table",
            details={},
        )


class RiskAnalyzer:
    """
    Analyzes Django migration operations and assigns risk scores.

    Risk scoring rules:
    0-1: Safe - No locks, backwards compatible
    2-3: Needs Review - May have performance impact or needs careful deployment
    4-5: Blocked - Causes locks, breaks backwards compatibility, or can't rollback
    """

    # Registry of operation analyzers
    ANALYZERS = {
        "AddField": AddFieldAnalyzer(),
        "RemoveField": RemoveFieldAnalyzer(),
        "DeleteModel": DeleteModelAnalyzer(),
        "AlterField": AlterFieldAnalyzer(),
        "RenameField": RenameFieldAnalyzer(),
        "RenameModel": RenameModelAnalyzer(),
        "AlterModelTable": AlterModelTableAnalyzer(),
        "AddIndex": AddIndexAnalyzer(),
        "AddConstraint": AddConstraintAnalyzer(),
        "RunSQL": RunSQLAnalyzer(),
        "RunPython": RunPythonAnalyzer(),
        "CreateModel": CreateModelAnalyzer(),
        "AlterUniqueTogether": AlterUniqueTogetherAnalyzer(),
        "AlterIndexTogether": AlterIndexTogetherAnalyzer(),
    }

    def analyze_migration(self, migration, path: str) -> MigrationRisk:
        operation_risks = []

        for op in migration.operations:
            risk = self.analyze_operation(op)
            operation_risks.append(risk)

        # Check for dangerous operation combinations
        combination_risks = self.check_operation_combinations(migration, operation_risks)

        return MigrationRisk(
            path=path,
            app=migration.app_label,
            name=migration.name,
            operations=operation_risks,
            combination_risks=combination_risks,
        )

    def analyze_operation(self, op) -> OperationRisk:
        op_type = op.__class__.__name__

        # Look up specific analyzer for this operation type
        analyzer = self.ANALYZERS.get(op_type)

        if analyzer:
            return analyzer.analyze(op)

        # Fallback for unknown operation types
        return OperationRisk(
            type=op_type,
            score=2,
            reason=f"Unknown operation type: {op_type}",
            details={},
        )

    def check_operation_combinations(self, migration, operation_risks: list[OperationRisk]) -> list[str]:
        """
        Check for dangerous combinations of operations in a single migration.

        Dangerous patterns:
        1. RunSQL with DML (UPDATE/DELETE) + schema changes = long transaction with locks
        2. RunSQL + DDL should be isolated
        3. Multiple schema changes in non-atomic migration
        """
        warnings = []

        # Categorize operations with indices for reference
        has_runsql_dml = False
        has_runsql_ddl = False
        has_schema_changes = False
        runsql_ops = []
        schema_change_ops = []
        dml_ops = []
        ddl_ops = []

        for idx, op_risk in enumerate(operation_risks):
            if op_risk.type == "RunSQL":
                runsql_ops.append((idx, op_risk))
                # Check SQL content
                sql_upper = str(op_risk.details.get("sql", "")).upper() if op_risk.details else ""
                if any(kw in sql_upper for kw in ["UPDATE", "DELETE", "INSERT"]):
                    has_runsql_dml = True
                    dml_ops.append((idx, op_risk))
                if any(kw in sql_upper for kw in ["CREATE INDEX", "ALTER TABLE", "ADD COLUMN"]):
                    has_runsql_ddl = True
                    ddl_ops.append((idx, op_risk))

            # Schema-changing operations
            if op_risk.type in [
                "AddField",
                "RemoveField",
                "AlterField",
                "RenameField",
                "AddIndex",
                "AddConstraint",
                "CreateModel",
                "DeleteModel",
            ]:
                has_schema_changes = True
                schema_change_ops.append((idx, op_risk))

        # Check for dangerous combinations
        if has_runsql_dml and has_schema_changes:
            # Build reference to involved operations
            dml_refs = ", ".join(f"#{idx+1} {op.type}" for idx, op in dml_ops)
            schema_refs = ", ".join(f"#{idx+1} {op.type}" for idx, op in schema_change_ops)
            warnings.append(
                f"❌ CRITICAL: {dml_refs} + {schema_refs}\n"
                "   RunSQL with DML (UPDATE/DELETE/INSERT) combined with schema changes. "
                "This creates a long-running transaction that holds locks for the entire duration. "
                "Split into separate migrations: 1) schema changes, 2) data migration."
            )

        if has_runsql_ddl and len(operation_risks) > 1:
            ddl_refs = ", ".join(f"#{idx+1} {op.type}" for idx, op in ddl_ops)
            warnings.append(
                f"⚠️  WARNING: {ddl_refs} mixed with other operations\n"
                "   RunSQL with DDL (CREATE INDEX/ALTER TABLE) should be isolated in their own migration "
                "to avoid lock conflicts."
            )

        if len(runsql_ops) > 0 and not getattr(migration, "atomic", True):
            warnings.append(
                "⚠️  INFO: Migration is marked atomic=False. Ensure data migrations handle failures correctly."
            )

        return warnings


class Command(BaseCommand):
    help = "Analyze migration operations and classify risk levels"

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-blocked",
            action="store_true",
            help="Exit with code 1 if any blocked migrations found",
        )

    def handle(self, *args, **options):
        migration_paths = self.get_migration_paths()

        if not migration_paths:
            self.stdout.write("No migrations to analyze")
            return

        results = self.analyze_migrations(migration_paths)

        if not results:
            self.stdout.write("No migrations analyzed")
            return

        self.print_report(results)

        if options["fail_on_blocked"]:
            blocked = [r for r in results if r.level == RiskLevel.BLOCKED]
            if blocked:
                sys.exit(1)

    def get_migration_paths(self) -> list[str]:
        """Read migration paths from stdin"""
        return MigrationDiscovery.read_paths_from_stdin()

    def analyze_migrations(self, migration_paths: list[str]) -> list[MigrationRisk]:
        """Analyze a list of migration file paths"""
        analyzer = RiskAnalyzer()
        results = []

        # Process paths and load migrations using shared utility
        loaded_migrations = MigrationDiscovery.process_migration_paths(
            migration_paths,
            skip_invalid=False,
            fail_on_ci=True,
        )

        # Analyze each migration
        for migration_info, migration in loaded_migrations:
            risk = analyzer.analyze_migration(migration, migration_info.path)
            results.append(risk)

        return results

    def print_report(self, results: list[MigrationRisk]):
        safe = [r for r in results if r.level == RiskLevel.SAFE]
        review = [r for r in results if r.level == RiskLevel.NEEDS_REVIEW]
        blocked = [r for r in results if r.level == RiskLevel.BLOCKED]

        print("\n" + "=" * 80)
        print("Migration Risk Report")
        print("=" * 80)
        print(f"\nSummary: {len(safe)} Safe | {len(review)} Needs Review | {len(blocked)} Blocked\n")

        if blocked:
            level = RiskLevel.BLOCKED
            print(f"{level.color}{level.icon} {level.category.upper()}\033[0m")
            print()
            for risk in blocked:
                self.print_migration_detail(risk)

        if review:
            level = RiskLevel.NEEDS_REVIEW
            print(f"\n{level.color}{level.icon} {level.category.upper()}\033[0m")
            print()
            for risk in review:
                self.print_migration_detail(risk)

        if safe:
            level = RiskLevel.SAFE
            print(f"\n{level.color}{level.icon} {level.category.upper()}\033[0m")
            print()
            for risk in safe:
                self.print_migration_detail(risk)

        print()

    def print_migration_detail(self, risk: MigrationRisk):
        print(f"{risk.path}")

        # Print individual operations with tree structure
        for idx, op_risk in enumerate(risk.operations):
            # Add connecting line if there are combination risks and not the last operation
            prefix = "  │  " if risk.combination_risks and idx < len(risk.operations) - 1 else "  "

            details_str = ", ".join(
                f"{k}: {v}"
                for k, v in op_risk.details.items()
                if k != "sql"  # Don't print full SQL
            )
            if details_str:
                print(f"{prefix}└─ #{idx+1} {op_risk.type} (score: {op_risk.score})")
                print(f"{prefix}   {op_risk.reason}")
                print(f"{prefix}   {details_str}")
            else:
                print(f"{prefix}└─ #{idx+1} {op_risk.type} (score: {op_risk.score}): {op_risk.reason}")

        # Print combination warnings with connecting visual
        if risk.combination_risks:
            print("  │")
            print("  └──> \033[91m⚠️  COMBINATION RISKS:\033[0m")
            for warning in risk.combination_risks:
                # Word wrap long warnings
                import textwrap

                wrapped = textwrap.fill(warning, width=72, initial_indent="       ", subsequent_indent="       ")
                print(wrapped)

        print()
