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

## The three mechanisms

### 1. Lazy API router

The DRF route aggregator (the router build plus ~200 viewset imports) used to run at _package import_ of `posthog.api`.
It now lives in `posthog/api/rest_router.py`, and `posthog/api/__init__.py` is a thin PEP 562 `__getattr__` shim that imports the aggregator only when a router object (`router`, `projects_router`, …) is first accessed — i.e. when the URLconf resolves, on the first web request.
Real submodules (`posthog.api.monitoring`, `.file_system`, …) resolve directly without building the aggregator, so a plain `django.setup()` stays cheap.

This is the laziness Django already intends: the URLconf is the entry point, and non-web processes never resolve it.

### 2. Model registration

Importing a viewset module used to be what registered some models (importing a model class runs `ModelBase.__new__` → `apps.register_model`).
With the router lazy, a model reachable _only_ through a viewset import silently disappears from `apps.get_models()` at setup time.
Every model must be imported from its app's `models/__init__.py` (or `models.py`) so it registers at app-population — independent of the router.

### 3. Signal receivers

Importing a viewset module also runs its `@receiver` decorators, so the eager router connected a pile of receivers as a side effect of `django.setup()`.
With the lazy router, those connect only when the router is first built — so any process that never builds it (celery, temporal, `migrate`, shell) silently loses them.
Wire receivers from the owning app's `AppConfig.ready()` instead, so they connect at setup.

## The regression guard

`posthog/test/test_startup_import_budget.py` boots a bare `django.setup()` in a clean subprocess and asserts three things, one per mechanism:

1. No `FORBIDDEN_AT_SETUP` heavy module (the lazy router aggregator, the AI core, `chdb`, `scipy`, …) is in `sys.modules`.
2. Every model registers at app-population — importing the router adds none.
3. No signal receiver connects _only_ when the router is built.

**When a guard fails, fix the import — do not widen the list.**
Defer the offending import, add the missing `models/__init__` import, or wire the receiver at `ready()`.
Widening the budget re-opens the door the guard exists to keep shut.

## Doing it right, and keeping it right

The startup path is a shared resource with no natural backpressure: nothing about adding a normal import _looks_ expensive, and the cost lands on processes you are not running locally.
Treat these as the defaults whenever you add backend code.

**Adding a new product or app.**
Register every model from `models/__init__.py`.
Wire signal receivers from `AppConfig.ready()`, not as a side effect of importing a viewset.
Keep `ready()` light — it runs in every process, so it must not import a heavy subsystem (see the next rule).

**Adding a signal receiver.**
Put it where it connects at setup: the owning `AppConfig.ready()`.
If the module holding the receiver also imports something heavy at module scope, do not import that module from `ready()` directly — either defer the heavy import inside the function that uses it, or move the receiver into a light module (`signals.py`) and import _that_ from `ready()`.
The test is simple: importing the module you wire at `ready()` should pull only light dependencies.

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

**Regenerating a shared snapshot on top of a bad merge.**
Query-count snapshot files (`.ambr`) are generated.
When both branches change one, neither side's version is correct for the merged code — regenerate against the merged branch rather than picking a side.
After regenerating, confirm it is not masking a regression: `makemigrations --check` clean, expected columns still present, and the query _set_ unchanged (a large "updated" count is usually benign renumbering when one query shifts position).

**Measuring the wrapper instead of the work.**
Timing a command that activates an env first folds activation cost into the number.
Measure inside the process.
And when a bare `python /tmp/script.py` cannot find the package, it is `sys.path` (the script's dir, not the repo) — set `PYTHONPATH`, do not conclude the env is broken.
