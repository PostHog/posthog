# ruff: noqa: T201 allow print statements

import os
import re
import sys
import select
from dataclasses import dataclass
from enum import Enum

from django.core.management.base import BaseCommand
from django.db import models
from django.db.migrations.loader import MigrationLoader


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

    @property
    def max_score(self) -> int:
        return max((op.score for op in self.operations), default=0)

    @property
    def level(self) -> RiskLevel:
        return RiskLevel.from_score(self.max_score)

    @property
    def category(self) -> str:
        return self.level.category


class RiskAnalyzer:
    """
    Analyzes Django migration operations and assigns risk scores.

    Risk scoring rules:
    0-1: Safe - No locks, backwards compatible
    2-3: Needs Review - May have performance impact or needs careful deployment
    4-5: Blocked - Causes locks, breaks backwards compatibility, or can't rollback
    """

    def analyze_migration(self, migration, path: str) -> MigrationRisk:
        operation_risks = []

        for op in migration.operations:
            risk = self.analyze_operation(op)
            operation_risks.append(risk)

        return MigrationRisk(
            path=path,
            app=migration.app_label,
            name=migration.name,
            operations=operation_risks,
        )

    def analyze_operation(self, op) -> OperationRisk:
        op_type = op.__class__.__name__

        score = 2  # Default for unknown operations
        reason = self.get_default_reason(op_type)
        details = {}

        if op_type == "AddField":
            field = op.field
            # Field is effectively nullable if null=True OR blank=True (for forms/API validation)
            is_nullable = field.null or getattr(field, "blank", False)
            has_default = field.default != models.NOT_PROVIDED

            if not is_nullable and not has_default:
                score = 5
                reason = "Adding NOT NULL field without default locks table"
            elif not is_nullable and has_default:
                score = 1
                reason = "Adding NOT NULL field with default (verify it's a constant)"
            else:
                score = 0
                reason = "Adding nullable field is safe"
            details["model"] = op.model_name
            details["field"] = op.name

        elif op_type == "RemoveField":
            score = 5
            reason = "Dropping column breaks backwards compatibility and can't rollback"
            details["model"] = op.model_name
            details["field"] = op.name

        elif op_type == "DeleteModel":
            score = 5
            reason = "Dropping table breaks backwards compatibility and can't rollback"
            details["model"] = op.name

        elif op_type == "AlterField":
            score = 3
            reason = "Field alteration may cause table locks or data loss"
            details["model"] = op.model_name
            details["field"] = op.name

        elif op_type == "RenameField":
            score = 4
            reason = "Renaming column breaks old code during deployment"
            details["model"] = op.model_name
            details["old"] = op.old_name
            details["new"] = op.new_name

        elif op_type == "RenameModel":
            score = 4
            reason = "Renaming table breaks old code during deployment"
            details["old"] = op.old_name
            details["new"] = op.new_name

        elif op_type == "AddIndex":
            if hasattr(op, "index"):
                concurrent = getattr(op.index, "concurrent", False)
                if not concurrent:
                    score = 4
                    reason = "Non-concurrent index creation locks table"
                else:
                    score = 0
                    reason = "Concurrent index is safe"

        elif op_type == "AddConstraint":
            score = 3
            reason = "Adding constraint may lock table (use NOT VALID pattern)"

        elif op_type == "RunSQL":
            sql = str(op.sql).upper()
            if "DROP" in sql:
                score = 5
                reason = "RunSQL with DROP is dangerous"
            elif "UPDATE" in sql or "DELETE" in sql:
                score = 4
                reason = "RunSQL with UPDATE/DELETE needs careful review for locking"
            elif "ALTER" in sql:
                score = 3
                reason = "RunSQL with ALTER may cause locks"
            else:
                score = 2
                reason = "RunSQL operation needs review"

        elif op_type == "RunPython":
            score = 2
            reason = "RunPython data migration needs review for performance"

        return OperationRisk(type=op_type, score=score, reason=reason, details=details)

    def get_default_reason(self, op_type: str) -> str:
        return f"{op_type} operation"


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
            blocked = [r for r in results if r.category == "Blocked"]
            if blocked:
                sys.exit(1)

    def get_migration_paths(self) -> list[str]:
        """Read migration paths from stdin"""
        if select.select([sys.stdin], [], [], 1)[0]:
            migration_paths = [line.strip() for line in sys.stdin.readlines() if line.strip()]
        else:
            if os.getenv("CI"):
                print("No migrations provided in CI")
                sys.exit(1)
            migration_paths = []

        return migration_paths

    def analyze_migrations(self, migration_paths: list[str]) -> list[MigrationRisk]:
        """Analyze a list of migration file paths"""
        analyzer = RiskAnalyzer()
        results = []

        loader = MigrationLoader(None)

        for path in migration_paths:
            if not path:
                continue
            if not path.endswith(".py"):
                print(f"Skipping non-Python file: {path}")
                continue
            if ".." in path or path.startswith("/"):
                print(f"Skipping suspicious path: {path}")
                continue

            try:
                app_label, migration_name = self.parse_migration_path(path)
                migration_key = (app_label, migration_name)

                if migration_key not in loader.disk_migrations:
                    print(f"Warning: Could not find migration {app_label}.{migration_name}")
                    continue

                migration = loader.disk_migrations[migration_key]

                risk = analyzer.analyze_migration(migration, path)
                results.append(risk)

            except Exception as e:
                print(f"Error analyzing {path}: {e}")
                if os.getenv("CI"):
                    sys.exit(1)

        return results

    def parse_migration_path(self, path: str) -> tuple[str, str]:
        products_match = re.findall(r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py", path)
        if products_match:
            app_label, migration_name = products_match[0]
            return app_label, migration_name

        generic_match = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", path)
        if generic_match:
            app_label, migration_name = generic_match[0]
            return app_label, migration_name

        raise ValueError(f"Could not parse migration path: {path}")

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
        for op_risk in risk.operations:
            details_str = ", ".join(f"{k}: {v}" for k, v in op_risk.details.items())
            if details_str:
                print(f"  └─ {op_risk.type} (score: {op_risk.score})")
                print(f"     {op_risk.reason}")
                print(f"     {details_str}")
            else:
                print(f"  └─ {op_risk.type} (score: {op_risk.score}): {op_risk.reason}")
        print()
