# Working on the sandboxed eval harness

Read [`README.md`](README.md) first for the module map and boot sequence.
This file is only the set of invariants that are easy to break and expensive to debug, because breaking most of them produces a hang or a silently wrong result rather than an exception.

Verify a change with `python -m ee.hogai.eval.sandboxed.harness --list` (imports every eval module, so it catches most breakage in seconds) before spending a real eval run on it.

## Import ordering

`__main__.py` calls `setup_django()` **before** importing `lifecycle`, and `lifecycle` is what pulls in everything that touches Django settings, the ORM, or the `products.tasks` facade.
Anything reachable from `__main__`'s top-level imports must therefore stay Django-free: today that is `cli.py`, `providers.py`, `tunnels.py`, `ports.py`, and `django_env.py` itself.

This is why the port constants live in `ports.py` rather than in `services.py`, which imports Django.
If you add an import to one of those modules, check that `--list` still runs.

## Concurrency

- **Never give Braintrust a `timeout`.** `EvalAsync`'s timeout wraps the whole task invocation, including time queued on our sandbox semaphore, so it would kill cases that never got a sandbox. The budget belongs in the `asyncio.wait_for` inside the slot.
- **Never let Braintrust's `max_concurrency` bind.** It is set to the case count so that `ctx.sandbox_slots` is the only limiter.
- **Acquire `ctx.sandbox_slots` exactly once per case**, around only the sandbox-owning window. It is not reentrant; a second acquisition inside the first deadlocks.
- Keep scoring, log parsing, and span building _outside_ the slot. A sandbox that is being scored is a sandbox that someone else could be using.
- Every sync Django ORM call reached from async code goes through `asyncio.to_thread`. Do not set `DJANGO_ALLOW_ASYNC_UNSAFE` to make an error go away.

## Terminal output

`ProgressReporter` owns stdout and holds a lock, because suites run concurrently and would otherwise interleave.
Do not add bare `print` calls to `base.py` or the harness; route them through the reporter.
The same lock guards the `eval_results.jsonl` append, where concurrent writes would tear a line in half.

`QUIET_REPORTER` exists so each Braintrust experiment does not dump its own score table into the shared stream.
Its callbacks are called synchronously by `EvalAsync` and must not be coroutines.

## Suites

Suites are discovered by convention, not registered: any coroutine named `eval_*` defined in a file named `eval_*.py` under `ee/hogai/eval/sandboxed/`.
A suite takes one argument, `ctx: EvalContext`, and returns `None`.

Because suites do not return their Braintrust result, `base.py` hands the summary to the reporter via `record_summary`.
That is the only path by which the final table and the JSONL export see per-scorer scores.

A crashing suite must never take down the others: `lifecycle._run_suite` catches `Exception` per suite and the run exits non-zero at the end.
Do not widen that to `BaseException`, which would swallow `CancelledError` and `KeyboardInterrupt`.

## Teardown

Bootstrap registers teardown on an `ExitStack` as each resource comes up, so a failure halfway through still unwinds what already started.
`atexit` hooks plus the subprocess manager's signal handlers cover Ctrl-C, where neither stack unwinds.

After any change, a Ctrl-C mid-run must leave no listeners on 18000 / 13308 / 18787 / 14040, no `task-sandbox-*` containers, and no Temporal dev server.
A finished case terminates its own sandbox; `provider.cleanup()` (via `atexit`) is the end-of-run safety net, sweeping any that a timeout, crash, or Ctrl-C left behind — leftover Docker containers by name, and leftover Modal sandboxes under the eval app (so they don't idle to their TTL).

## Providers

Provider differences belong in `providers.py`, not in `if provider == "docker"` branches scattered through `lifecycle.py`.
Add a `SandboxProviderStrategy` method rather than a conditional.

`preflight()` must catch a missing prerequisite before any infrastructure boots, and its message must say how to fix it.
A missing ngrok authtoken, for instance, otherwise surfaces only as a 60-second tunnel timeout.

The chosen provider must reach `settings.SANDBOX_PROVIDER` **before `django.setup()`**, which is why `__main__` sets it in the environment (from `SANDBOX_PROVIDER_SETTING`) rather than relying only on the async-phase `override_settings`.
`products.tasks` resolves the sandbox class from that setting exactly once and caches it in module globals, so the first `Sandbox` access wins for the whole process.
`.env` ships `SANDBOX_PROVIDER=docker`, so setting it late let a `--provider modal` run cache `DockerSandbox` and execute the agent in a local container while still pointing it at the ngrok URLs.
Docker mode hid this because the cached value already matched.

## pytest

This tree is excluded from pytest collection by `collect_ignore` in `ee/hogai/eval/conftest.py`.
Do not add a `conftest.py` here, do not import `pytest` in harness or eval modules, and remember that a test file placed under `sandboxed/` will never run.
`ci/` and `offline/` are still pytest, and share `ee/hogai/eval/conftest.py` with this tree, so options and fixtures there must keep working.
