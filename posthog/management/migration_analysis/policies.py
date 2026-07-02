"""PostHog-specific migration policies.

These are team coding guidelines, not database safety issues.
Policies enforce architectural decisions and coding standards.
"""

import re
from abc import ABC, abstractmethod
from pathlib import Path

from django.conf import settings
from django.db import models

from posthog.management.migration_analysis.operations import is_unmanaged_model

# Apps owned by PostHog where policies are enforced
POSTHOG_OWNED_APPS = ["posthog", "ee"]


def is_posthog_app(app_label: str, migration=None) -> bool:
    """Check if app is owned by PostHog (vs third-party dependency).

    Args:
        app_label: The Django app label (e.g., 'posthog', 'endpoints')
        migration: Optional migration class to check module path for product apps
    """
    if app_label in POSTHOG_OWNED_APPS:
        return True

    # Product apps have short labels like 'endpoints' but modules under 'products.*'
    # Check the migration's module path to detect product apps
    if migration is not None:
        module = getattr(migration, "__module__", "")
        if module.startswith("products."):
            return True

    return False


class MigrationPolicy(ABC):
    """Base class for PostHog migration policies."""

    @abstractmethod
    def check_operation(self, op) -> list[str]:
        """
        Check if operation violates this policy.

        Returns:
            List of violation messages (empty if compliant)
        """
        pass

    @abstractmethod
    def check_migration(self, migration) -> list[str]:
        """
        Check if entire migration violates this policy.

        Returns:
            List of violation messages (empty if compliant)
        """
        pass


class UUIDPrimaryKeyPolicy(MigrationPolicy):
    """
    PostHog policy: All new models must use UUID primary keys.

    Rationale:
    - Better for distributed systems (no coordination needed)
    - Security: No sequential/predictable IDs
    - Easier data merging and future sharding
    """

    def check_operation(self, op) -> list[str]:
        if op.__class__.__name__ != "CreateModel":
            return []

        # Check for integer primary key
        for field_name, field in op.fields:
            if field_name != "id":
                continue

            field_type = field.__class__.__name__
            if field_type in ["AutoField", "BigAutoField"]:
                return [
                    f"Model '{op.name}' uses integer ID ({field_type}). "
                    "PostHog requires UUID primary keys. "
                    "Use `from posthog.models.utils import UUIDModel` and inherit from UUIDModel."
                ]

        return []

    def check_migration(self, migration) -> list[str]:
        """Only enforce on PostHog-owned apps."""
        if not is_posthog_app(migration.app_label, migration):
            return []

        violations = []
        for op in migration.operations:
            violations.extend(self.check_operation(op))
        return violations


class AtomicFalsePolicy(MigrationPolicy):
    """
    Policy: atomic=False should only be used with CONCURRENTLY operations.

    Rationale:
    - atomic=False loses transaction rollback safety
    - Only CONCURRENTLY operations require it (can't run in transaction)
    - Using it for regular DDL creates partial-commit risk on failure
    - Our retry mechanism (bin/migrate) re-runs entire migration, breaking
      on non-idempotent operations that already committed
    """

    CONCURRENT_OP_TYPES = {
        "AddIndexConcurrently",
        "RemoveIndexConcurrently",
        # PostHog helpers (see posthog/migration_helpers/concurrent_index.py)
        "CreateIndexConcurrently",
        "DropIndexConcurrently",
        "SafeAddIndexConcurrently",
        "SafeRemoveIndexConcurrently",
    }

    def check_operation(self, op) -> list[str]:
        return []  # Checked at migration level

    def check_migration(self, migration) -> list[str]:
        if not is_posthog_app(migration.app_label, migration):
            return []

        is_atomic = getattr(migration, "atomic", True)
        has_concurrent = self._has_concurrent_operations(migration)
        has_non_concurrent = self._has_non_concurrent_operations(migration)

        violations = []

        # atomic=False without concurrent ops = warn (not block)
        # Some legitimate uses: long-running data migrations that need partial commits
        # But we want to discourage lazy use that breaks retry mechanism
        if not is_atomic and not has_concurrent:
            violations.append(
                "⚠️ WARNING: atomic=False without CONCURRENTLY operations. "
                "This loses transaction rollback safety. If migration fails midway, "
                "partial changes are committed and retry will fail on non-idempotent ops. "
                "Only use atomic=False if: (1) using CONCURRENTLY, or (2) intentional for "
                "long-running ops with idempotent SQL (IF NOT EXISTS, WHERE NOT EXISTS). "
                "Consider async migrations for large data backfills instead."
            )

        # concurrent ops without atomic=False = block (will fail at runtime anyway)
        if has_concurrent and is_atomic:
            violations.append(
                "❌ BLOCKED: CONCURRENTLY operations require atomic=False. "
                "PostgreSQL cannot run CREATE/DROP INDEX CONCURRENTLY inside a transaction. "
                "Add 'atomic = False' to the Migration class."
            )

        # Mixed: has both concurrent and non-concurrent ops = recommend splitting
        if not is_atomic and has_concurrent and has_non_concurrent:
            violations.append(
                "⚠️ RECOMMEND SPLIT: Migration mixes CONCURRENTLY operations with regular DDL. "
                "Split into separate migrations: (1) regular operations with atomic=True (default), "
                "(2) CONCURRENTLY operations with atomic=False. "
                "This ensures regular DDL has rollback safety while CONCURRENTLY can run outside a transaction."
            )

        return violations

    def _has_non_concurrent_operations(self, migration) -> bool:
        """Check if migration has operations that are NOT concurrent index operations."""
        non_concurrent_types = {
            "AddField",
            "RemoveField",
            "AlterField",
            "RenameField",
            "CreateModel",
            "DeleteModel",
            "RenameModel",
            "AddConstraint",
            "RemoveConstraint",
            "AlterModelTable",
            "AlterUniqueTogether",
            "AlterIndexTogether",
            "RunPython",
        }

        for op in migration.operations:
            op_type = op.__class__.__name__

            # Check if it's a non-concurrent operation type
            if op_type in non_concurrent_types:
                return True

            # RunSQL that doesn't contain CONCURRENTLY
            if op_type == "RunSQL":
                sql = str(getattr(op, "sql", ""))
                if "CONCURRENTLY" not in sql.upper():
                    return True

            # AddIndex without concurrent=True
            if op_type == "AddIndex":
                if not (hasattr(op, "index") and getattr(op.index, "concurrent", False)):
                    return True

            # Check inside SeparateDatabaseAndState
            if op_type == "SeparateDatabaseAndState":
                for db_op in getattr(op, "database_operations", []) or []:
                    db_op_type = db_op.__class__.__name__
                    if db_op_type in non_concurrent_types:
                        return True
                    if db_op_type == "RunSQL":
                        sql = str(getattr(db_op, "sql", ""))
                        if "CONCURRENTLY" not in sql.upper():
                            return True
                    # AddIndex without concurrent=True inside SeparateDatabaseAndState
                    if db_op_type == "AddIndex":
                        if not (hasattr(db_op, "index") and getattr(db_op.index, "concurrent", False)):
                            return True

        return False

    def _has_concurrent_operations(self, migration) -> bool:
        for op in migration.operations:
            if self._is_concurrent_operation(op):
                return True

            # Also check inside SeparateDatabaseAndState
            if op.__class__.__name__ == "SeparateDatabaseAndState":
                for db_op in getattr(op, "database_operations", []) or []:
                    if self._is_concurrent_operation(db_op):
                        return True

        return False

    def _is_concurrent_operation(self, op) -> bool:
        """Check if a single operation is a CONCURRENTLY operation."""
        # Check Django concurrent operations
        if op.__class__.__name__ in self.CONCURRENT_OP_TYPES:
            return True

        # Check RunSQL for CONCURRENTLY keyword
        if op.__class__.__name__ == "RunSQL":
            sql = str(getattr(op, "sql", ""))
            if "CONCURRENTLY" in sql.upper():
                return True

        # Check AddIndex with concurrent=True
        if op.__class__.__name__ == "AddIndex":
            if hasattr(op, "index") and getattr(op.index, "concurrent", False):
                return True

        return False


class ConcurrentIndexIdempotencyPolicy(MigrationPolicy):
    """
    Policy: concurrent index operations must be idempotent.

    Rationale:
    - bin/migrate re-runs the ENTIRE migration on failure, with exponential
      backoff, up to MIGRATE_MAX_RETRIES times.
    - CREATE/DROP INDEX CONCURRENTLY is non-transactional and runs with
      atomic=False, so a cancelled or interrupted build leaves an INVALID
      index behind - there is no transaction to roll it back.
    - Django's AddIndexConcurrently / RemoveIndexConcurrently emit a bare
      CREATE/DROP INDEX CONCURRENTLY with no IF [NOT] EXISTS and give no way
      to disable lock_timeout. Deploy runs under a lock_timeout, so a single
      transient cancellation leaves an invalid index, and every subsequent
      retry then fails with "relation already exists" (or "does not exist"
      for drops). The migration is stuck and blocks deploys until the invalid
      index is cleaned up by hand.
    - The safe pattern is RunSQL with `SET lock_timeout = 0;` plus
      `CREATE INDEX CONCURRENTLY IF NOT EXISTS` (and the matching
      `DROP INDEX CONCURRENTLY IF EXISTS` reverse), wrapped in
      SeparateDatabaseAndState so Django model state still tracks the index.
      lock_timeout = 0 stops the build from being cancelled in the first
      place; IF NOT EXISTS makes the retry idempotent if it is.
    """

    DJANGO_CONCURRENT_OPS = {"AddIndexConcurrently", "RemoveIndexConcurrently"}

    # The PostHog helpers in posthog/migration_helpers/concurrent_index.py
    # encode the idempotency guarantees this policy enforces (indisvalid
    # recovery + IF [NOT] EXISTS + timeout disabling) at the operation
    # level, so they are explicitly exempt from the static SQL check.
    POSTHOG_SAFE_HELPER_OPS = {
        "CreateIndexConcurrently",
        "DropIndexConcurrently",
        "SafeAddIndexConcurrently",
        "SafeRemoveIndexConcurrently",
    }

    GUIDANCE = (
        "Use posthog.migration_helpers.SafeAddIndexConcurrently (or\n"
        "SafeRemoveIndexConcurrently). It takes a model_name + Index like Django's\n"
        "AddIndexConcurrently, tracks Django state itself (no SeparateDatabaseAndState),\n"
        "disables lock_timeout/statement_timeout, skips if a valid index already exists,\n"
        "and rebuilds an invalid leftover from a prior interrupted build:\n"
        "\n"
        "    from posthog.migration_helpers import SafeAddIndexConcurrently\n"
        "\n"
        "    SafeAddIndexConcurrently(\n"
        '        model_name="mymodel",\n'
        '        index=models.Index(fields=["field_name"], name="my_idx"),\n'
        "    )\n"
        "\n"
        "If the index doesn't map to a Django Index, use CreateIndexConcurrently\n"
        "(raw SQL) wrapped in SeparateDatabaseAndState with a matching AddIndex. Raw\n"
        "RunSQL with `SET lock_timeout = 0; CREATE INDEX CONCURRENTLY IF NOT EXISTS ...`\n"
        "is still accepted as a last-resort fallback.\n"
        "\n"
        "See https://github.com/PostHog/posthog/blob/master/docs/published/handbook/engineering/safe-django-migrations.md#adding-indexes"
    )

    def check_operation(self, op) -> list[str]:
        return []  # Checked at migration level

    def check_migration(self, migration) -> list[str]:
        if not is_posthog_app(migration.app_label, migration):
            return []

        violations = []
        for op in self._iter_executed_operations(migration):
            violations.extend(self._check_single_operation(op))
        return violations

    def _iter_executed_operations(self, migration):
        """Yield operations that emit SQL, descending recursively into
        SeparateDatabaseAndState.database_operations.

        SDAS can legally nest (a database_operations entry can itself be a
        SeparateDatabaseAndState); a non-recursive descent would silently skip
        the inner ops and reopen the incident class. state_operations never
        touch the database, so they are not descended.
        """
        yield from self._descend(migration.operations)

    def _descend(self, ops):
        for op in ops or []:
            if op.__class__.__name__ == "SeparateDatabaseAndState":
                yield from self._descend(getattr(op, "database_operations", []) or [])
            else:
                yield op

    def _check_single_operation(self, op) -> list[str]:
        op_type = op.__class__.__name__

        if op_type in self.POSTHOG_SAFE_HELPER_OPS:
            # The helpers handle indisvalid recovery + IF [NOT] EXISTS +
            # timeout disabling internally. Trust the type, skip the SQL
            # check (which would false-positive on the helper's display SQL).
            return []

        if op_type in self.DJANGO_CONCURRENT_OPS:
            return [
                f"❌ BLOCKED: {op_type} emits a non-idempotent CREATE/DROP INDEX CONCURRENTLY "
                "and cannot disable lock_timeout. A single transient lock_timeout cancellation "
                "during deploy leaves an INVALID index; bin/migrate then re-runs the migration "
                'and every retry fails with "relation already exists" - a stuck migration that '
                f"blocks deploys.\n{self.GUIDANCE}"
            ]

        if op_type == "RunSQL":
            return self._check_runsql(op)

        return []

    def _check_runsql(self, op) -> list[str]:
        # Both forward `sql` and `reverse_sql` flow through bin/migrate's retry
        # loop (rollbacks rerun on failure too), so a non-idempotent reverse
        # reopens the same stuck-migration class as a non-idempotent forward.
        violations = []
        violations.extend(self._check_sql(getattr(op, "sql", ""), "sql"))
        violations.extend(self._check_sql(getattr(op, "reverse_sql", ""), "reverse_sql"))
        return violations

    # Match the specific concurrent-index statement, not the whole RunSQL blob.
    # Substring checks (`"IF NOT EXISTS" in sql`) false-negative when an unrelated
    # statement in the same RunSQL legitimately uses IF [NOT] EXISTS (e.g.
    # `CREATE TABLE IF NOT EXISTS ...; CREATE INDEX CONCURRENTLY idx ...`).
    _BARE_CREATE_INDEX_CONCURRENTLY = re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\b(?!\s+IF\s+NOT\s+EXISTS\b)",
        re.IGNORECASE,
    )
    _BARE_DROP_INDEX_CONCURRENTLY = re.compile(
        r"DROP\s+INDEX\s+CONCURRENTLY\b(?!\s+IF\s+EXISTS\b)",
        re.IGNORECASE,
    )

    def _check_sql(self, sql, attr_name: str) -> list[str]:
        sql = str(sql)
        # Strip /* */, -- and # comments so keywords inside comments don't match
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
        sql = re.sub(r"--[^\n]*", "", sql)
        sql = re.sub(r"#[^\n]*", "", sql)

        violations = []
        if self._BARE_CREATE_INDEX_CONCURRENTLY.search(sql):
            violations.append(
                f"❌ BLOCKED: RunSQL {attr_name} CREATE INDEX CONCURRENTLY is missing IF NOT EXISTS, "
                "so it is non-idempotent. A cancelled build leaves an INVALID index and every "
                f'bin/migrate retry then fails with "relation already exists".\n{self.GUIDANCE}'
            )
        if self._BARE_DROP_INDEX_CONCURRENTLY.search(sql):
            violations.append(
                f"❌ BLOCKED: RunSQL {attr_name} DROP INDEX CONCURRENTLY is missing IF EXISTS, "
                "so it is non-idempotent. After a partial failure every bin/migrate retry then "
                f'fails with "index does not exist".\n{self.GUIDANCE}'
            )
        return violations


class HotTableAlterPolicy(MigrationPolicy):
    """
    Policy: DDL on hot tables must be explicitly acknowledged.

    Rationale:
    - posthog_team, posthog_user, posthog_organization, and posthog_project are
      read on virtually every request.
    - Any ALTER TABLE on them needs an ACCESS EXCLUSIVE lock. While that lock
      request waits behind in-flight queries, every later query on the table
      queues behind it - so even a metadata-only ADD COLUMN of a nullable
      column can stall site-wide traffic until lock_timeout cancels it, and
      each bin/migrate retry repeats the stall. This has caused production
      5xx incidents.
    - Most new team fields should not be on Team at all: a Team extension
      model (posthog/models/team/README.md) only creates a new table, which
      takes no lock on posthog_team.
    - When DDL on a hot table is genuinely needed, the author accepts the risk
      by adding "<app_label>.<migration_name>" to
      hot_table_acknowledged_migrations.txt - a deliberate, reviewable act
      that also coordinates the deploy.
    """

    HOT_MODELS = {"team", "user", "organization", "project"}

    # Op types that carry the target model in `model_name`
    FIELD_LEVEL_OPS = {
        "AddField",
        "RemoveField",
        "AlterField",
        "RenameField",
        "AddConstraint",
        "RemoveConstraint",
        "AddIndex",
        "RemoveIndex",
        # ADD CONSTRAINT ... NOT VALID still takes a brief ACCESS EXCLUSIVE lock,
        # so the helper is gated like a plain AddConstraint. (ValidateConstraint
        # is not listed - VALIDATE takes only SHARE UPDATE EXCLUSIVE.)
        "AddConstraintNotValid",
        # AddForeignKeyNotValid(model_name=<hot table>) emits ALTER TABLE posthog_*
        # ADD CONSTRAINT against the hot *child* itself - same lock hazard. Gating on
        # model_name catches that; the helper's sanctioned use (a FK *pointing at* a
        # hot parent) carries the parent in to_table, not model_name, so it stays
        # unflagged here.
        "AddForeignKeyNotValid",
    }
    # Op types that carry the target model in `name`
    MODEL_LEVEL_OPS = {
        "DeleteModel",
        "RenameModel",
        "AlterModelTable",
        "AlterUniqueTogether",
        "AlterIndexTogether",
    }

    ACKNOWLEDGMENTS_FILE = Path(__file__).with_name("hot_table_acknowledged_migrations.txt")

    # Only ALTER TABLE is matched; CONCURRENTLY index builds take SHARE UPDATE EXCLUSIVE, which
    # doesn't block reads or writes. Mirrors the Postgres grammar: ALTER TABLE [ IF EXISTS ]
    # [ ONLY ] [ schema. ] name, with optional double-quoting on the schema and table identifiers.
    _ALTER_HOT_TABLE = re.compile(
        r"ALTER\s+TABLE\s+"
        r"(?:IF\s+EXISTS\s+)?"
        r"(?:ONLY\s+)?"
        r'(?:"?\w+"?\s*\.\s*)?'  # optional schema qualifier, e.g. public.
        r'"?(posthog_team|posthog_user|posthog_organization|posthog_project)"?\b',
        re.IGNORECASE,
    )

    def check_operation(self, op) -> list[str]:
        return []  # Checked at migration level (needs the migration label for the acknowledgment hint)

    def check_migration(self, migration) -> list[str]:
        if not is_posthog_app(migration.app_label, migration):
            return []

        label = f"{migration.app_label}.{migration.name}"
        if label in self._acknowledged_migrations():
            return []

        violations = []
        for op in self._descend(migration.operations):
            # Unmanaged models (managed=False) map external tables - Django emits no DDL and
            # no FK constraint, so they can't take the hot-table lock this policy gates.
            if is_unmanaged_model(op, migration):
                continue
            fk_table = self._fk_target_hot_table(op)
            if fk_table:
                violations.append(self._fk_violation(op, fk_table, label))
                continue
            table = self._hot_table_target(op, migration.app_label)
            if table:
                violations.append(self._violation(op, table, label))
        return violations

    def _acknowledged_migrations(self) -> set[str]:
        if not self.ACKNOWLEDGMENTS_FILE.exists():
            return set()
        lines = self.ACKNOWLEDGMENTS_FILE.read_text().splitlines()
        return {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}

    def _descend(self, ops):
        """Yield operations that emit SQL, descending into SeparateDatabaseAndState.database_operations.

        state_operations never touch the database, so they are not descended.
        """
        for op in ops or []:
            if op.__class__.__name__ == "SeparateDatabaseAndState":
                yield from self._descend(getattr(op, "database_operations", []) or [])
            else:
                yield op

    def _hot_table_target(self, op, app_label: str) -> str | None:
        """Return the hot table an operation alters directly, or None.

        FK *targets* (a CreateModel/AddField pointing at a hot table) are handled
        upstream in check_migration via _fk_target_hot_table, not here.
        """
        op_type = op.__class__.__name__

        # The hot models all live in the posthog app; same-named models in
        # product apps map to different tables.
        if app_label == "posthog":
            model_name = None
            if op_type in self.FIELD_LEVEL_OPS:
                model_name = getattr(op, "model_name", None)
            elif op_type in self.MODEL_LEVEL_OPS:
                model_name = getattr(op, "name", None)
            if model_name and model_name.lower() in self.HOT_MODELS:
                return f"posthog_{model_name.lower()}"

        # Hand-written DDL can hit a hot table from any app
        if op_type == "RunSQL":
            for attr in ("sql", "reverse_sql"):
                table = self._hot_table_in_sql(getattr(op, attr, ""))
                if table:
                    return table

        return None

    def _fk_target_hot_table(self, op) -> str | None:
        """Return the hot table a CreateModel/AddField FK points at, or None.

        Skips FKs declared with db_constraint=False - those emit no FK constraint
        and take NO lock on the parent, so they're the sanctioned escape hatch.

        AlterField that turns a column into a hot-table FK is the same hazard class
        but a rarer shape; it's intentionally out of scope here.
        """
        op_type = op.__class__.__name__
        if op_type == "CreateModel":
            fields = getattr(op, "fields", None) or []
            for _name, field in fields:
                table = self._fk_field_hot_table(field)
                if table:
                    return table
        elif op_type == "AddField":
            table = self._fk_field_hot_table(getattr(op, "field", None))
            if table:
                return table
        return None

    def _fk_field_hot_table(self, field) -> str | None:
        # A ManyToManyField with an auto-created through table emits FK constraints to the
        # target, taking the same SHARE ROW EXCLUSIVE lock on the parent. An explicit
        # `through=` model defines its own FK fields, which get analyzed when that model's
        # CreateModel runs - skip it here so it isn't double-counted. db_constraint=False on
        # the M2M propagates to the through FKs, so it's the same escape hatch as a plain FK.
        if isinstance(field, models.ManyToManyField):
            if getattr(field.remote_field, "through", None) is not None:
                return None
            if getattr(field.remote_field, "db_constraint", True) is False:
                return None
            return self._resolve_fk_target_table(field.remote_field.model)
        if not isinstance(field, models.ForeignKey):
            return None
        if getattr(field, "db_constraint", True) is False:
            return None  # db_constraint=False takes no lock on the parent; the escape hatch
        return self._resolve_fk_target_table(field.remote_field.model)

    def _resolve_fk_target_table(self, target) -> str | None:
        """Resolve a FK target to a hot posthog_* table name, or None.

        `field.remote_field.model` is a string label like "posthog.team" in
        migration state. settings.AUTH_USER_MODEL (the swappable user FK) desugars
        to that same "posthog.user" string at serialization time, so both the
        explicit and swappable forms land here as strings.
        """
        if target == settings.AUTH_USER_MODEL:
            target = "posthog.user"
        if not isinstance(target, str) or "." not in target:
            return None
        app, _, model_name = target.rpartition(".")
        if app.lower() == "posthog" and model_name.lower() in self.HOT_MODELS:
            return f"posthog_{model_name.lower()}"
        return None

    def _hot_table_in_sql(self, sql) -> str | None:
        sql = str(sql)
        # Strip /* */, -- and # comments so table names inside comments don't match
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
        sql = re.sub(r"--[^\n]*", "", sql)
        sql = re.sub(r"#[^\n]*", "", sql)

        for statement in sql.split(";"):
            # VALIDATE CONSTRAINT only takes SHARE UPDATE EXCLUSIVE, which doesn't block reads or writes
            if "VALIDATE CONSTRAINT" in statement.upper():
                continue
            match = self._ALTER_HOT_TABLE.search(statement)
            if match:
                return match.group(1).lower()
        return None

    def _violation(self, op, table: str, label: str) -> str:
        return (
            f'❌ BLOCKED: {op.__class__.__name__} on "{table}" - this table is read on virtually every '
            "request. Any ALTER TABLE on it takes an ACCESS EXCLUSIVE lock; while that lock request waits "
            "behind in-flight queries, every later query on the table queues behind it, so even a "
            "metadata-only ADD COLUMN can stall site-wide traffic until lock_timeout cancels it - and "
            "each bin/migrate retry repeats the stall. This has caused production 5xx incidents.\n"
            "Prefer not altering this table at all: new domain-specific team fields belong on a Team "
            "extension model (see posthog/models/team/README.md), which only creates a new table.\n"
            f'If this change genuinely must alter {table}, add "{label}" to '
            "posthog/management/migration_analysis/hot_table_acknowledged_migrations.txt to accept the "
            "risk, and coordinate the deploy with #team-infrastructure for a low-traffic window.\n"
            "See https://github.com/PostHog/posthog/blob/master/docs/published/handbook/engineering/safe-django-migrations.md#altering-hot-tables"
        )

    def _fk_violation(self, op, table: str, label: str) -> str:
        return (
            f'❌ BLOCKED: {op.__class__.__name__} adds a ForeignKey to "{table}" - this table is read on '
            "virtually every request. Creating the FK constraint takes a SHARE ROW EXCLUSIVE lock on the "
            f"referenced parent ({table}), which conflicts with the ROW EXCLUSIVE lock every "
            "INSERT/UPDATE/DELETE on it holds. Under write traffic the lock request queues, lock_timeout "
            "cancels it, and each bin/migrate retry repeats the stall. This has blocked deploys.\n"
            "Two options:\n"
            "(a) db_constraint=False on the ForeignKey - emits no FK constraint and takes NO lock on the "
            "parent at all (app-level enforcement only). This is the only truly lock-free path.\n"
            "(b) For a real database constraint, declare the FK with db_constraint=False, then add it back "
            "as a DB constraint via posthog.migration_helpers.AddForeignKeyNotValid in a later migration and "
            "ValidateForeignKey after that. NOT VALID still takes a *brief* SHARE ROW EXCLUSIVE lock on the "
            "parent for the metadata add (it skips the row scan), so it shrinks the lock window but does not "
            "eliminate it; VALIDATE then runs lock-free on the parent.\n"
            f'If this FK genuinely must lock {table} on add, add "{label}" to '
            "posthog/management/migration_analysis/hot_table_acknowledged_migrations.txt to accept the "
            "risk, and coordinate the deploy with #team-infrastructure for a low-traffic window.\n"
            "See https://github.com/PostHog/posthog/blob/master/docs/published/handbook/engineering/safe-django-migrations.md#foreign-keys-to-hot-tables"
        )


# DevEx meta-principle for anyone adding a policy here: when a pattern is risky but
# common, the goal is not to document a clever safe workaround and trust authors to
# hand-roll it - it's to ship a drop-in helper in posthog/migration_helpers that bakes
# in the safe behavior, then point this policy's violation message at that helper. A
# blocked migration with a "use SafeAddIndexConcurrently" / "use AddForeignKeyNotValid"
# message reaches for one import; a wall of hand-written RunSQL with caveats reopens the
# incident class. Prefer the helper-plus-pointer over documenting complexity.

# Registry of all PostHog policies
POSTHOG_POLICIES = [
    UUIDPrimaryKeyPolicy(),
    AtomicFalsePolicy(),
    ConcurrentIndexIdempotencyPolicy(),
    HotTableAlterPolicy(),
]
