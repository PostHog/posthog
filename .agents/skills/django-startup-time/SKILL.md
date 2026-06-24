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

Full background — the four mechanisms (lazy router, model registration, receiver wiring, boot GC window), the regression guards, how to add code without regressing them, how to measure, and the detailed trap write-ups: **[docs/internal/django-startup-time.md](../../../docs/internal/django-startup-time.md)**. That doc is the single source of detail; this skill is the trigger and the checklist.

The guards live in `posthog/test/test_startup_import_budget.py`. **When one fails, defer the import — don't remove an entry to dodge it.** Conversely, when you deliberately defer a significant heavy lib off setup, **add it to `FORBIDDEN_AT_SETUP`** (after confirming it's absent from a bare `django.setup()`). New imports nobody has named yet are caught by `test_no_new_heavy_imports_at_setup`: any package not in `posthog/test/setup_import_baseline.txt` costing ≥100ms at setup fails the build — defer it; baseline only what every process genuinely needs at setup.

## Defaults when adding backend code

- New app/product: register models from `models/__init__.py`, wire receivers from `AppConfig.ready()`, keep `ready()` light.
- New receiver: wire it at the owning `AppConfig.ready()`, from a dedicated light module (`activity_logging.py`, `signals.py`) — never via the API/viewset module, even if it looks light today; those accumulate heavy imports and `ready()` silently inherits them.
- New heavy dependency (vendor SDK, Temporal/AI/ClickHouse, pandas/pyarrow/scipy): import it function-locally on the path that uses it with `# noqa: PLC0415`, never at module scope.
- Schema types on a setup-path module: enums from `posthog.schema_enums` (cheap); pydantic models from `posthog.schema` only inside the method that uses them. No module-level `from posthog.tasks...` on setup paths — `CeleryQueue` lives in `posthog.celery_queues`.
- New viewset/route: it no longer loads at setup — don't rely on import side effects; routes go in `rest_router.py`, not the `__init__.py` shim.
- Any deferral relocates cost — ask which process pays now, on what path, and whether that path is latency-sensitive (background workers paying lazily: fine; web workers paying on first requests: usually not).

## Traps to check before you commit

One line each — the doc has the full write-up and the fix recipe for every entry.

- **`ready()` re-drags a heavy dep onto startup** — importing a receiver's module runs its module-level imports too; re-measure after wiring.
- **Silent receiver loss** — lost receivers don't error; reproduce in a process that does NOT build the router (`manage.py shell`, celery, `migrate`).
- **Models vanishing from the registry** — a model reachable only via a viewset import breaks `makemigrations`/admin/mypy; import it from `models/__init__.py`, then `dmypy stop`.
- **Lazy-router merge conflicts** — keep the `__init__.py` shim, port master's aggregator deltas into `rest_router.py`.
- **Aggregator package `__init__`s** — shim with PEP 562 `__getattr__`, via `importlib.import_module` and an `__all__` whitelist (catch-alls recurse or deadlock on sibling imports).
- **Serializer field kwargs run at import** — `choices=...` inputs can't be function-locally deferred; move the constant to an import-light module.
- **Vanished re-exports** — regenerating/shimming a module drops names other code imported from it incidentally (e.g. `schema.BaseModel`); grep for consumers of the old namespace, including relative-import spellings.
- **Patch targets break on call-time imports** — `@patch("mod.helper")` stops intercepting once `mod` imports `helper` at call time; patch the defining module instead.
- **Snapshot regen on a bad merge** — regenerate `.ambr` against the merged branch, then confirm it isn't masking a regression.
- **Measuring the wrapper, not the work** — time inside the process; `importtime` + `tuna`, not pyinstrument; `grimp` for cycles and door enumeration.
- **Phantom importtime costs from GC** — re-capture with `gc.disable()`; if the cost vanishes, the finding is GC, not the module. Keep the entrypoints' GC window closing in a `finally`.
