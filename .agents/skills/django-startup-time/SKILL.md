---
name: django-startup-time
description: >
  Keep heavy imports off the django.setup() path that every process (web, celery, temporal,
  migrate, shell, CI) pays for. Use when touching AppConfig.ready(), wiring signal receivers,
  editing the lazy API router (posthog/api/rest_router.py or its __init__.py shim), deferring a
  heavy import, when the startup-import-budget guard fails, or when merging master into a
  long-lived branch that made the router lazy.
---

# Django startup time

Full background — the three mechanisms (lazy router, model registration, receiver wiring), the regression guard, how to add code without regressing it, and how to measure: **[docs/internal/django-startup-time.md](../../../docs/internal/django-startup-time.md)**.

Read that doc first. The guard is `posthog/test/test_startup_import_budget.py`; **when it fails, defer the import — do not widen the budget list.**

## Defaults when adding backend code

- New app/product: register models from `models/__init__.py`, wire receivers from `AppConfig.ready()`, keep `ready()` light.
- New receiver: wire it at the owning `AppConfig.ready()`; if its module imports something heavy, defer that import inside the function or move the receiver to a light `signals.py`.
- New heavy dependency (vendor SDK, Temporal/AI/ClickHouse, pandas/pyarrow/scipy): import it function-locally on the path that uses it with `# noqa: PLC0415`, never at module scope.
- New viewset/route: it no longer loads at setup — don't rely on import side effects; routes go in `rest_router.py`, not the `__init__.py` shim.

## Traps to check before you commit

- **`ready()` re-drags a heavy dep onto startup.** Importing a receiver's module in `ready()` runs its module-level imports too; if one is heavy (billing/Stripe, Temporal, AI core), startup pays for it. Defer the heavy import inside the method, or wire from a light module. **Re-measure** — easy to get backwards.
- **Silent receiver loss.** Lost receivers don't error; the symptom is a quiet downstream failure. Reproduce in a process that does NOT build the router: `manage.py shell`, celery, `migrate` — not the web server.
- **Models vanishing from the registry.** A model reachable only via a viewset import disappears at setup → breaks `makemigrations`, admin, and django-stubs mypy. Import it from the app's `models/__init__.py`. After such a change, `dmypy stop` before re-running mypy.
- **Lazy-router merge conflicts.** Master edits the old eager `posthog/api/__init__.py`; on the branch that file is the shim and the aggregator is `rest_router.py`. Keep the shim, diff the merge base against the incoming aggregator, port the import + route deltas into `rest_router.py`, and re-point any moved receiver's wiring to its product `AppConfig.ready()`.
- **Snapshot regen on a bad merge.** Regenerate `.ambr` against the merged branch, then confirm it's not masking a regression (`makemigrations --check` clean, columns intact).
- **Measuring the env wrapper, not the work.** Time inside the process with `perf_counter`, `TEST=1` to skip runtime I/O; `python -X importtime` + `tuna` for cost, not pyinstrument. When a deferral is blocked by a circular import, `grimp` (`nominate_cycle_breakers`) ranks which edge to cut.
