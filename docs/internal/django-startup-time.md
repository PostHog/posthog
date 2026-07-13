# Django startup time

`django.setup()` runs on every process: web, but also celery, temporal, `migrate`, `manage.py shell`, and every CI job.
Heavy imports dragged onto that path are paid by all of them.
This doc explains how we keep heavy subsystems off the startup path, the guard that enforces it, how to add code without regressing it, and the traps that have repeatedly caused follow-up fixes.

## The shape of the problem

The cost is almost entirely _module imports_, not runtime work.
A single eager `import` chain reaching the AI core, the batch-export Temporal framework, embedded ClickHouse (`chdb`), `scipy`, or the Stripe SDK adds hundreds of ms each.
The fix is always the same: make the import lazy so it loads only when its code actually runs.

The biggest single lever was the **lazy API router** (below).
Everything else is deferring individual heavy imports off the startup path.

## The five mechanisms

### 1. Lazy API router

The DRF route aggregator (the router build plus ~200 viewset imports) used to run at _package import_ of `posthog.api`.
It now lives in `posthog/api/rest_router.py`, and `posthog/api/__init__.py` is a thin PEP 562 `__getattr__` shim that imports the aggregator only when a router object (`router`, `projects_router`, …) is first accessed — i.e. when the URLconf resolves, on the first web request.
Real submodules (`posthog.api.monitoring`, `.file_system`, …) resolve directly without building the aggregator, so a plain `django.setup()` stays cheap.

This is the laziness Django already intends: the URLconf is the entry point, and non-web processes never resolve it.

Web is the exception and resolves it eagerly: `wsgi.py`/`asgi.py` build the URLconf at import, pre-fork, inside the GC window — because the k8s probes (`/_livez`, `/_readyz`) are served by short-circuiting middleware and never resolve URLs, each worker would otherwise build the router on its **first live request** (measured at multiple seconds per worker, after every deploy).
Pre-building lands the router in the frozen heap, copy-on-write-shared across workers — exactly the pre-lazy-router behavior for web, while every other process keeps the win.
`test_web_entrypoint_prebuilds_the_router` pins this; a prefork smoke (gunicorn `--preload`, 4 workers) verified workers inherit the built router and serve cold requests without it.

### 2. Model registration

Importing a viewset module used to be what registered some models (importing a model class runs `ModelBase.__new__` → `apps.register_model`).
With the router lazy, a model reachable _only_ through a viewset import silently disappears from `apps.get_models()` at setup time.
Every model must be imported from its app's `models/__init__.py` (or `models.py`) so it registers at app-population — independent of the router.

### 3. Signal receivers

Importing a viewset module also runs its `@receiver` decorators, so the eager router connected a pile of receivers as a side effect of `django.setup()`.
With the lazy router, those connect only when the router is first built — so any process that never builds it (celery, temporal, `migrate`, shell) silently loses them.
Wire receivers from the owning app's `AppConfig.ready()` instead, so they connect at setup.

### 4. Garbage collection deferred during boot

Boot allocations are almost all permanent — modules, classes, registries, the generated pydantic schema — so the cyclic GC has nothing useful to reclaim while `django.setup()` runs, yet allocation thresholds trigger ~470 collections during it (~300ms of pauses, single gen2 passes up to ~100ms).
The entrypoints that own a setup (`manage.py`, `posthog/wsgi.py`, `posthog/asgi.py`) wrap it in `gc.disable()` → boot → `gc.freeze()` → `gc.enable()`.
The freeze moves the ~600k surviving boot objects to the permanent generation, so they are excluded from every future full collection — which also makes post-boot work (management-command discovery, the first router build) collect almost for free, and maximizes copy-on-write page sharing when a prototype process forks workers.
There is deliberately no `gc.collect()` before the freeze: a full pass over the boot heap costs ~210ms and reclaims only ~4% of objects (a few MB), so the garbage is frozen along with everything else.
The window must always close — GC left disabled in a long-lived process means unbounded cycle growth — hence the `try`/`finally` and the guard test asserting `gc.isenabled()` and a nonzero freeze count after a `manage.py` boot.
Pytest processes get the same window via a dedicated early-loaded plugin, `pytest_boot_gc.py`, registered with `-p pytest_boot_gc` in `pytest.ini`.
`-p` plugins load before pytest-django's `load_initial_conftests` hook, which is what runs `django.setup()`, so the disable is already in effect when setup's several million permanent allocations happen.
The root conftest still closes the window (freeze, re-enable, threshold tuning) via `_end_gc_boot_window` at collection finish; its own `gc.disable()` call stays as a fallback for test configs that do not load the plugin (e.g. `ee/pytest.ini`).
This saves ~0.2–0.4s per test process.
Celery's `django.setup()` happens inside its Django fixup, not in an entrypoint we own, so celery workers do not get the window yet.

### 5. Generated schema and query layer evicted from setup

`posthog.schema` (the generated pydantic data model, ~2s to import) and the HogQL/query-runner layer used to load during `django.setup()` because dozens of model files and `ready()` chains imported them at module scope.
They now load only in processes that actually run queries: web pods still pay at boot (the wsgi/asgi URLconf prewarm builds the router pre-fork, behind readiness), while celery, temporal, migrate, shell, and CI start without them.
Two pieces make this hold:
the enums (~270 classes) live in `posthog.schema_enums`, a separate generated module that imports in ~20ms — `bin/split-schema-enums.py` extracts them as a post-generation step of `hogli build:schema`, and `posthog.schema` re-exports every name so existing imports keep working;
everything else got one of the standard treatments — enum-only imports repointed to `posthog.schema_enums`, annotation-only model uses moved under `TYPE_CHECKING` with quoted annotations, method-body uses imported at call time.
The default when writing a model file or any other setup-path module: take enums from `posthog.schema_enums`; if you need an actual pydantic model, import it inside the method that uses it.
The same applies to the celery task graph: `posthog/tasks/__init__.py` eagerly imports every task module so autodiscovery registers them, so any module-level `from posthog.tasks...` import on a setup path drags all of them in — import tasks at the call site, and take `CeleryQueue` from `posthog.celery_queues` (import-light, made for decorator-eval consumers).

## The regression guard

`posthog/test/test_startup_import_budget.py` boots a bare `django.setup()` in a clean subprocess and asserts three things, one per mechanism:

1. No `FORBIDDEN_AT_SETUP` heavy module (the lazy router aggregator, the generated `posthog.schema`, the query-runner layer, the AI core, `chdb`, `scipy`, …) is in `sys.modules`.
2. Every model registers at app-population — importing the router adds none.
3. No signal receiver connects _only_ when the router is built.

**When a guard fails, fix the import — do not widen the list.**
Defer the offending import, add the missing `models/__init__` import, or wire the receiver at `ready()`.
Removing an entry to make the test pass re-opens the door the guard exists to keep shut.

The list cuts both ways: when you _deliberately_ defer a significant heavy library off the startup path, **add it to `FORBIDDEN_AT_SETUP`** so the win can't silently regress.
Removing an entry to dodge a failure weakens the guard; adding one to lock in a deferral strengthens it.
Confirm the module is absent from a bare `django.setup()` first, then add it.

**The forward-looking guard: new heavy imports.**
`FORBIDDEN_AT_SETUP` only catches modules someone already named; `test_no_new_heavy_imports_at_setup` catches the heavy import nobody has named yet.
It captures `python -X importtime` over a bare setup (GC disabled, so a migrating gen2 pause can't masquerade as a module's cost), aggregates self-time by top-level package for third-party (SDKs split across submodules; the package total is the meaningful number) and per-module for first-party, and fails when a name **not** in `posthog/test/setup_import_baseline.txt` costs ≥100ms.
There are deliberately no per-entry time budgets — absolute timings flake in CI — time is only the materiality gate for _new arrivals_: known names are never timed, and a new arrival is deterministic (the PR that adds the import, adds it).
Two captures are taken and the per-name minimum used, because a cold first boot pays page-cache misses that can double a package's apparent cost.
When it fires: defer the import (the failure message carries the playbook); baseline a package only when every process genuinely needs it during setup, with a justifying comment.

## Doing it right, and keeping it right

The startup path is a shared resource with no natural backpressure: nothing about adding a normal import _looks_ expensive, and the cost lands on processes you are not running locally.
Treat these as the defaults whenever you add backend code.

**Adding a new product or app.**
Register every model from `models/__init__.py`.
Wire signal receivers from `AppConfig.ready()`, not as a side effect of importing a viewset.
Keep `ready()` light — it runs in every process, so it must not import a heavy subsystem (see the next rule).

**Adding a signal receiver.**
Put it where it connects at setup: the owning `AppConfig.ready()`.
If the module holding the receiver also imports something heavy at module scope, do not import that module from `ready()` directly — either defer the heavy import inside the function that uses it, or move the receiver into a light module (`signals.py`, `activity_logging.py`) and import _that_ from `ready()`.
The test is simple: importing the module you wire at `ready()` should pull only light dependencies.
Prefer the dedicated light module even when the owning module looks light _today_ — API/viewset modules accumulate module-scope imports, and `ready()` silently inherits whatever they gain.
The batch-exports `ready()` wired its receiver through the API module on a "the module is light" justification; the module later picked up imports reaching every destination's vendor SDK, and `django.setup()` quietly grew ~1.6s.

**Adding a heavy dependency** (a vendor SDK, a Temporal/AI/ClickHouse path, anything pulling pandas/pyarrow/scipy).
If it is used on one code path, import it function-locally at that path with `# noqa: PLC0415`, not at module scope.
A module-level import is "free" to write but is paid by every process that transitively imports the module, forever.

**Adding a viewset or route.**
It will not load at `django.setup()` anymore.
Do not rely on importing it for any side effect (model registration, receiver wiring, monkeypatching) — those must live somewhere that loads at setup.
New routes go in `posthog/api/rest_router.py` (or a product's `register_routes`), never back in the `__init__.py` shim.

**When you are unsure whether something is heavy.**
Measure (next section).
A 30-second `importtime` run settles it; guessing does not.

**How it stays right over time.**
The guard runs in CI on every PR, so a regression is caught at review, not in production.
The standing rule when it goes red is always _defer, don't widen_ — the list is a ratchet, and every entry that moves the wrong way gives back a permanent slice of the win.
Re-profile occasionally even when the guard is green: the guard only catches the specific heavy modules it names, and the floor drifts up as the codebase grows.
When the floor has crept, the lever is the same as it ever was — find the heaviest cumulative import that is not actually needed at setup, and defer it.

## Measuring

- Wall-clock: `time.perf_counter()` around `django.setup()` _inside_ the process.
  Do not time the shell wrapper — env activation is not part of the number.
- Set `TEST=1 DEBUG=1` so `ready()` skips redis/runtime I/O; you want import cost, which is identical in test mode, not environment-dependent network round-trips.
- Import cost breakdown: `python -X importtime` + `tuna` for the tree.
  Rank modules by _self_ time for leaf cost, _cumulative_ for subtree cost.
  **Not** pyinstrument — it smears import cost across `importlib._bootstrap` frames.
- **Importtime self-times can lie: a GC pause lands on whatever module happens to be executing.**
  A ~100ms gen2 collection fires wherever the allocation counter crosses its threshold, and `importtime` books it as that module's self-time — a 400-line module of dict literals showed 117ms, and the phantom _migrates between modules when import order changes_ (two runs of the same code attributed it to two different modules).
  Before deferring a suspiciously expensive module, sanity-check it: a pure-Python module with no heavy imports should cost microseconds.
  The decisive test is re-capturing with `gc.disable()` in front — if the cost vanishes, the module is innocent and the finding is GC, not imports.
- Finding the _trigger_ of a heavy load: monkeypatch `builtins.__import__` to print the stack the first time the target module is imported.
  A profile shows cost but never whether it is _removable_ — confirm with an A/B, because a module is often reachable by more than one path and cutting one changes nothing.
- Import _structure_, when a deferral is blocked: `grimp` builds the module import graph.
  Sometimes you cannot just defer a heavy import because it is load-bearing in a circular import — deferring one edge only relocates the cycle.
  `grimp`'s `nominate_cycle_breakers` ranks which edge to cut, so the real work becomes untangling the owning package's cycle before the heavy import can come off the startup path.

## Traps (these have all caused follow-up fixes)

**`ready()` that re-drags a heavy subsystem onto startup.**
The most common regression.
You wire a receiver by importing its owning module in `AppConfig.ready()`, but that module imports a heavy dependency at module scope (a billing/Stripe client, the Temporal framework, the AI core).
The receiver connects — and so does the heavy import, defeating the whole point.
Fix: defer the heavy import _inside_ the method that uses it (`# noqa: PLC0415`), or extract the receiver into a light module that the `ready()` imports instead.
Always re-measure: wiring a receiver and cutting startup time are easy to get backwards.

**Silent receiver loss.**
When receivers stop connecting, nothing errors — the symptom is downstream and quiet (a cache that stops invalidating, cleanup that stops running on background writes).
It will not show up in a smoke test of the web server, because the web server builds the router.
Reproduce in a process that does _not_: `manage.py shell`, a celery worker, `migrate`.

**Models that vanish from the registry.**
A model only reachable via a viewset import disappears at setup.
The failure is indirect: `makemigrations` stops seeing it, admin drops it, and the django-stubs mypy plugin (which builds its model registry via `django.setup()`) reports `"type[X]" has no attribute "objects"`.
Add the model to its app's `models/__init__.py`.

**Stale `dmypy` after a registration change.**
The django-stubs mypy plugin caches its `django.setup()` snapshot in the daemon.
After changing what registers at setup, `dmypy stop` before re-running, or you will chase phantom errors against the old model registry.

**Semantic merge conflicts against the lazy router.**
Long-lived branches that move the aggregator into `rest_router.py` keep colliding with master, which still edits the old eager `posthog/api/__init__.py` (product migrations move viewset modules out of `posthog/api` into `products/`).
Git puts master's aggregator deltas in the `__init__.py` conflict, but on the branch that file is the shim.
Recipe: keep the shim (`--ours` on `__init__.py`), diff the merge base against the incoming version of the old aggregator to get the exact import + route-registration deltas, and port them into `rest_router.py`.
When a module carrying a `ready()`-wired receiver moves, re-point the wiring to its new product's `AppConfig.ready()` and keep any heavy import deferred.
The same shape bites whenever one side moves or renames a module the other side references at module scope — a text-clean merge that breaks on import.

**Removing an eager import chain unmasks latent circular imports.**
The eager router imported a large chain when `posthog/urls.py` loaded, _before_ urls.py reached its own product imports.
That chain often imported some module fully and early, accidentally papering over a circular import elsewhere that only ever worked because of that import order.
Make the router lazy and the accidental pre-import disappears, so the next process to import the URLconf hits the cycle head-on.
The real example: `slack_app.backend.api` imports workflow classes from `posthog_code_slack_mention`, which imported a helper straight back from `slack_app.backend.api` at module scope (placed late with `# noqa: E402` — a tell that someone already fought the ordering).
With the pre-import gone, Django's system checks (`check_custom_error_handlers` imports the URLconf, e.g. during `ensure_migration_defaults`) raised `cannot import name ... from partially initialized module`.
Two things make this nasty: it surfaces far from the change (a migration-defaults step in one CI job, not the lazy-router files), and the buggy code is not yours — so it is tempting to blame master.
Do not assume: the decisive test is `django.setup()` then `import_module("posthog.urls")` in a clean subprocess, run on a detached `origin/master` worktree _and_ the branch.
If only the branch fails, you unmasked it and you own the fix — break the cycle by deferring the back-reference to its call sites.

**A package `__init__` that aggregates its submodules taxes every submodule import.**
A worker-facing aggregator (`temporal/__init__.py` importing all destinations to build `WORKFLOWS` / `ACTIVITIES`) makes _any_ `import <pkg>.<submodule>` execute the whole aggregation — Python runs parent package `__init__`s first.
Importing one constants table from one destination loaded thirteen vendor SDKs.
Fix: move the aggregator to a submodule (`workflows.py`) and make the `__init__` a PEP 562 `__getattr__` shim.
Two gotchas in that shim, both found the hard way:
`from <pkg> import workflows` _inside_ the package's own `__getattr__` recurses forever (`_handle_fromlist` re-enters `__getattr__`) — use `importlib.import_module`.
And a catch-all `__getattr__` is wrong: `from <pkg> import <anything>` probes the package attribute first, so a catch-all eagerly loads the aggregator on every such probe — including for submodule names, which deadlocks if any aggregated module imports a sibling through the package root (`record_batch_model` importing `sql` did exactly this, masked for years by the eager init's import order).
Whitelist the public names (`if name in __all__`) and raise `AttributeError` otherwise, so submodule imports fall back to normal resolution.

**DRF serializer field kwargs are evaluated at import.**
`choices=sorted(SUPPORTED_THINGS)` in a serializer field runs at class definition, i.e. when the module imports — you cannot function-locally defer the import it depends on.
If the constant lives in a heavy module (a Temporal destination, an SDK wrapper), move the constant to an import-light module and have both sides import it from there; re-export under the old name to keep existing importers working.

**A deferral relocates cost — check where it lands before calling it a win.**
Deferring an import does not delete the work; it moves it to first use, and first use may be a live request.
The general question to ask of any deferral: _which process pays now, on what path, and is that path latency-sensitive?_
Background workers paying lazily is almost always fine; web workers paying on first requests usually is not.

**Pydantic `defer_build` on the generated schema: attempted and reverted.**
Generating `posthog.schema` against a `defer_build` base took ~400ms of core-schema construction off every setup, and looked safe — validation, `model_dump`, `model_json_schema`, and `TypeAdapter` all build on demand in round-trip tests.
Two failures killed it.
First, cost relocation (above): in a web pod the deferred builds land on each worker's first `/query` after every deploy — previously paid at boot, behind the readiness probe, pre-fork and COW-shared — and the obvious warm-up loop measured ~2.5x more expensive than eager class creation (`model_rebuild()` re-resolves namespaces per model).
Second, and fatal: query runners _construct_ response models directly (no validation, so nothing triggers the lazy build), and `model_dump()` then feeds a deferred child model's mock serializer into pydantic-core through a polymorphic field — `TypeError: 'MockValSer' object cannot be converted to 'SchemaSerializer'`, a hard 500 in any process.
Round-trip tests on a single model cannot catch this: for `defer_build`, the serialization _matrix_ (construct-then-dump, subclass-through-parent, `Any`-typed fields) is the test surface.
The ~1.8s the schema cost at import was real but structural — it was eventually removed by evicting the module from setup entirely (mechanism 5), not by deferring builds.

**Vanished re-exports.**
When a module stops importing a name at module scope (moved under `TYPE_CHECKING`, deferred to call time, or dropped by regeneration), every `from that_module import name` elsewhere breaks — and the consumers are invisible until import time, because they were importing the name _incidentally_ through a module that merely happened to hold it.
The eviction hit this with `from posthog.hogql.modifiers import HogQLQueryModifiers` in test files: fine for years, ImportError the day modifiers stopped binding the name.
Before unbinding a name, grep for every import form — including `from package import module` and relative `from ...schema import` spellings, which a `^from posthog\.schema import` regex misses — and repoint consumers to the defining module.

**Tests that patch a module attribute break when the import moves to call time.**
`@patch("some.module.helper")` works by replacing the _attribute on the module object_; a function that does `from elsewhere import helper` at call time never reads that attribute, so the patch silently stops intercepting and the real code runs in the test.
This caused three rounds of follow-up fixes in one week (conversations person lookup and groups lookup, the LLM-gateway policy task, the subscription free-tier constant).
Fix the test, not the deferral: patch the name where it is _read_ — the defining module (`@patch("posthog.hogql.query.execute_hogql_query")`), which the call-time import resolves at call time, after the patch is in place.
For a lazy module constant resolved via PEP 562 `__getattr__`, read it through `getattr(sys.modules[__name__], ...)` rather than as a bare global so a patched attribute still takes effect.

**Regenerating a shared snapshot on top of a bad merge.**
Query-count snapshot files (`.ambr`) are generated.
When both branches change one, neither side's version is correct for the merged code — regenerate against the merged branch rather than picking a side.
After regenerating, confirm it is not masking a regression: `makemigrations --check` clean, expected columns still present, and the query _set_ unchanged (a large "updated" count is usually benign renumbering when one query shifts position).

**Measuring the wrapper instead of the work.**
Timing a command that activates an env first folds activation cost into the number.
Measure inside the process.
And when a bare `python /tmp/script.py` cannot find the package, it is `sys.path` (the script's dir, not the repo) — set `PYTHONPATH`, do not conclude the env is broken.
