# Code Review: Migration Risk Analyzer Updates

## Critical Issues

None identified. The core logic appears sound with no critical security risks or data corruption issues.

## Functional Gaps

- **L64 in analyzer.py**: Potential NPE if `database_operations` exists but is None/empty. Add null check:

```diff
- if op.__class__.__name__ == "SeparateDatabaseAndState" and hasattr(op, "database_operations"):
+ if op.__class__.__name__ == "SeparateDatabaseAndState" and hasattr(op, "database_operations") and op.database_operations:
```

- **L63-65 in analyze_migration_risk.py**: The auto-detection returns ALL unapplied migrations, but CI workflow still fails with --fail-on-blocked. This could block CI for migrations from third-party packages that are risky but necessary. Consider filtering to only PostHog migrations in CI context.

- **Missing edge case handling**: The `get_unapplied_migrations()` method doesn't handle database connection failures. Add try/except:

```diff
def get_unapplied_migrations(self) -> list[tuple[str, object]]:
    """Get all unapplied migrations using Django's migration executor."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

+   try:
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
+   except Exception as e:
+       # Return empty list if can't connect to DB (e.g., in CI without DB)
+       return []

    return [(f"{migration.app_label}.{migration.name}", migration) for migration, backwards in plan]
```

- **CI workflow inconsistency**: Lines 228-231 in ci-backend.yml run the analyzer with `--fail-on-blocked` but then check for "FAILED" string. The command will exit(1) on blocked migrations, not print "FAILED". This error handling is redundant/incorrect.

## Improvements Suggested

- **L57 in analyze_migration_risk.py**: The `app_counts` dictionary building could use `defaultdict(int)` for cleaner code:

```python
from collections import defaultdict
app_counts = defaultdict(int)
for _label, migration in migrations:
    app_counts[migration.app_label] += 1
```

- **L168-177 in analyzer.py**: The multiple high-risk operations check uses score >= 4, but this threshold is hardcoded. Consider making it a class constant for maintainability.

- **CI workflow optimization**: The workflow now runs migration analysis twice - once for PR comment (line 228) and once for failing CI (line 266 removed). Consider consolidating to run once and use the result for both purposes.

- **Per-app policy message**: The error message in policies.py could be clearer about which apps are affected when multiple apps have violations.

## Positive Observations

- **Smart auto-detection**: Replacing stdin-based discovery with Django's MigrationExecutor is excellent - more reliable and catches third-party migrations automatically.
- **Per-app counting fix**: The SingleMigrationPolicy change correctly handles the real-world scenario where a PR might include migrations from multiple apps (e.g., PostHog + dependency).
- **Comprehensive combination checks**: The new RunPython+schema, multiple high-risk, and multiple indexes checks are valuable for catching problematic patterns.
- **Clean separation**: The OperationCategorizer properly tracks different operation types with clear property methods.

## Overall Assessment

**Request Changes** - While the implementation is mostly solid, there are functional gaps that need addressing:

1. Add null/empty check for `database_operations` in SeparateDatabaseAndState handling
2. Fix or simplify the CI workflow error handling logic (the FAILED check is incorrect)
3. Add error handling for database connection failures in `get_unapplied_migrations()`
4. Consider filtering migrations to PostHog-only in CI context to avoid blocking on third-party migrations

The auto-detection approach is a significant improvement, but needs these edge cases handled before merging.
