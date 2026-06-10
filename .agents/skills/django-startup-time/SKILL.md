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

Read that doc first. The guard is `posthog/test/test_startup_import_budget.py`. **When it fails, defer the import — don't remove an entry to dodge it.** Conversely, when you deliberately defer a significant heavy lib off setup, **add it to `FORBIDDEN_AT_SETUP`** (after confirming it's absent from a bare `django.setup()`) so the win can't silently regress. New imports nobody has named yet are caught by `test_no_new_heavy_imports_at_setup`: any package not in `posthog/test/setup_import_baseline.txt` costing ≥100ms at setup fails the build — defer it; baseline only what every process genuinely needs at setup.

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
- **Aggregator package `__init__`s.** An `__init__.py` that imports all submodules (e.g. a Temporal `WORKFLOWS`/`ACTIVITIES` aggregator) makes every `import <pkg>.<submodule>` pay for everything. Move the aggregator to a submodule and shim the `__init__` with PEP 562 `__getattr__` — but use `importlib.import_module` (the `from <pkg> import x` form recurses inside a package `__getattr__`) and whitelist public names with `if name in __all__` (a catch-all intercepts submodule-import probes and deadlocks on siblings that import via the package root).
- **Serializer field kwargs run at import.** `choices=...` evaluates at class definition — its inputs can't be function-locally deferred; move the constant to an import-light module instead.
- **Snapshot regen on a bad merge.** Regenerate `.ambr` against the merged branch, then confirm it's not masking a regression (`makemigrations --check` clean, columns intact).
- **Measuring the env wrapper, not the work.** Time inside the process with `perf_counter`, `TEST=1` to skip runtime I/O; `python -X importtime` + `tuna` for cost, not pyinstrument. When a deferral is blocked by a circular import, `grimp` (`nominate_cycle_breakers`) ranks which edge to cut.
- **Phantom importtime costs from GC.** A gen2 pause is booked as self-time of whatever module was executing, and migrates between modules as import order changes. A pure-Python module showing ~100ms is suspect — re-capture with `gc.disable()` in front; if the cost vanishes, the finding is GC, not the module. The boot entrypoints (`manage.py`, `wsgi.py`, `asgi.py`) already defer GC around setup (`gc.disable()` → boot → `gc.freeze()` → `gc.enable()`); keep that window closing in a `finally`.
