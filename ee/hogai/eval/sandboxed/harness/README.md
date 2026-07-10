# The sandboxed eval harness

This package is the runner for `ee/hogai/eval/sandboxed/`.
For how to _use_ it, read [`../README.md`](../README.md).
For the rules to preserve when _changing_ it, read [`AGENTS.md`](AGENTS.md).
This file explains how it fits together.

## Why it exists

The sandboxed evals need heavy shared infrastructure: a committed test database, an in-process Django server the sandbox can call back into, an LLM gateway, an MCP server, and a Temporal server plus worker.
Under pytest that infrastructure lived in session fixtures, and suites ran strictly one at a time, with Braintrust parallelizing only _within_ a suite.
Wall-clock was dominated by suites queueing behind each other while sandbox capacity sat idle.

The harness boots the same infrastructure once, then runs every suite concurrently on a single event loop and bounds total load with one global semaphore.
Braintrust remains the eval engine and reporting backend; it just no longer controls scheduling.

## Modules

| Module            | Role                                                                                                                 |
| ----------------- | -------------------------------------------------------------------------------------------------------------------- |
| `__main__.py`     | Entry point. Parses args, configures Django, then hands off to `lifecycle`.                                          |
| `cli.py`          | `HarnessOptions` and the argparse builder. Resolves per-provider defaults.                                           |
| `ports.py`        | The four port constants. Deliberately free of Django imports.                                                        |
| `providers.py`    | `SandboxProviderStrategy` and its docker/modal implementations: preflight, settings overrides, sandbox TTL, cleanup. |
| `tunnels.py`      | `NgrokTunnels`. Modal only: generates an ngrok config, starts the agent, waits for public URLs.                      |
| `django_env.py`   | `setup_django()`, the `NullDbBlocker` shim, and `EvalDatabase` (test database lifecycle).                            |
| `live_server.py`  | `EvalLiveServer`, a session-lifetime Django `LiveServerThread`.                                                      |
| `services.py`     | Starts the LLM gateway and MCP server subprocesses; builds local skills.                                             |
| `temporal_env.py` | Local Temporal dev server, stale-workflow cleanup, and the worker thread.                                            |
| `demo_data.py`    | `SandboxedDemoData`: seeds the master Hedgebox team once, then mints an isolated team per case.                      |
| `discovery.py`    | Walks the tree for `eval_*.py` and collects `eval_*` coroutines into `EvalSuite` objects.                            |
| `context.py`      | `EvalContext`, the single object every suite receives.                                                               |
| `reporting.py`    | `ProgressReporter`, the final summary table, and the quiet Braintrust reporter.                                      |
| `lifecycle.py`    | `SandboxedEvalHarness`: orchestrates bootstrap, the run, and teardown.                                               |

## Boot sequence

Discovery happens first, before anything is provisioned, so a typo'd selector costs a module import rather than a database build.

The bootstrap is deliberately synchronous and runs before any event loop exists, because it is ORM-heavy and Django's async-safety guard rejects sync ORM calls from an async context:

1. `setup_django()` sets `DEBUG` / `TEST` / `IN_EVAL_TESTING`, then `django.setup()` and `setup_test_environment()`.
2. `EvalDatabase.setup()` creates the `default` test database and drives PostHog's own eval database setup (persons database, ClickHouse).
3. `EvalLiveServer` binds `0.0.0.0:18000`.
4. The LLM gateway (`:13308`) and MCP server (`:18787`) start as subprocesses.
5. Modal only: ngrok tunnels come up, exposing all three services publicly.
6. Local skills are built. Docker bind-mounts them; Modal bakes them into the image it builds.
7. The master Hedgebox team is seeded.

The async phase then starts the Temporal dev server on the main loop, applies the provider's settings overrides, terminates stale workflows, starts the Temporal worker on its own thread and loop, and fans the suites out with `asyncio.gather`.

Teardown unwinds an `ExitStack` and an `AsyncExitStack` in reverse.
`atexit` hooks and the subprocess manager's signal handlers cover the Ctrl-C path, where neither stack unwinds.

## Concurrency model

One `asyncio.Semaphore` on `EvalContext` bounds live sandboxes across every suite.
`base.py::task()` acquires it around exactly the sandbox-owning window and releases it before post-processing.

Two consequences worth internalizing:

- The per-case timeout is an `asyncio.wait_for` **inside** the slot. Braintrust's own `timeout` would have wrapped the whole task invocation, including time queued on the semaphore, killing cases that never got a sandbox.
- A second, smaller `demo_slots` semaphore bounds concurrent ClickHouse demo-data copies. On modal the sandbox semaphore is effectively unbounded, so it can no longer double as that protection.

There are two event loops. The main loop owns the Temporal dev server, the suites, and the reporter.
The Temporal worker keeps its own loop on a daemon thread, and the two communicate only through `loop.call_soon_threadsafe`.

## Provider differences

|                     | docker                        | modal                    |
| ------------------- | ----------------------------- | ------------------------ |
| `SANDBOX_PROVIDER`  | `docker`                      | `MODAL_DOCKER`           |
| Service URLs        | `host.docker.internal:<port>` | ngrok public URLs        |
| Local skills        | bind-mounted                  | baked into the image     |
| Default sandbox cap | 4                             | unbounded                |
| Sandbox TTL         | default                       | case timeout plus margin |
| End-of-run cleanup  | container sweep               | none needed locally      |

`MODAL_DOCKER` is the same `ModalSandbox` class under a dedicated Modal app name, so local DEBUG image builds do not pollute the production app's image cache.

The modal TTL override exists because under `TEST=1` the sandbox TTL equals the default per-case timeout, which would let Modal reap a slow case's sandbox exactly as it was finishing.
