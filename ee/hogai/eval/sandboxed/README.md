# Sandboxed agent evals

These evals run the real coding agent inside a real sandbox against a seeded Hedgebox project, then score what it did.
Each eval case gets its own isolated org/team/user, so cases never see each other's state.

Unlike `ee/hogai/eval/ci/`, this tree does **not** run under pytest.
It runs on a standalone harness that boots the shared infrastructure once (test database, Django live server, LLM gateway, MCP server, Temporal) and then runs every selected suite concurrently.
See [`harness/README.md`](harness/README.md) for how that works internally.

Two other docs sit next to this one:

- [`AGENTS.md`](AGENTS.md) is the Hedgebox dataset reference. Read it before writing eval cases: your `expected` values and scorers must match that taxonomy exactly.
- [`harness/AGENTS.md`](harness/AGENTS.md) lists the invariants to preserve when changing the harness itself.

## Running

```bash
hogli evals:sandboxed [SELECTOR ...] [flags]
```

Or invoke the harness module directly (run it from a flox shell so `cargo` and the venv are available):

```bash
python -m ee.hogai.eval.sandboxed.harness [SELECTOR ...] [flags]
```

No manual env sourcing is needed on either path.
The harness loads the repo-root `.env` itself (shell values win), and `hogli evals:sandboxed` additionally layers in `.env.local` / `.env.development` / `.env.services` through hogli's standard env loading — including 1Password resolution when `.env.local` holds `op://` references.
Before any infrastructure boots, a preflight validates that the required variables are set (`SANDBOX_JWT_PRIVATE_KEY`, `LLM_GATEWAY_ANTHROPIC_API_KEY`, `BRAINTRUST_API_KEY`) and fails with a one-line fix per missing variable.

Selectors are substrings matched against a suite id of the form `<domain>/<module>::<fn>`, for example `experiments`, `sql`, or `eval_lifecycle_skills`.
Omit them to run every suite.
An unmatched selector fails immediately, before anything is provisioned.

The harness needs the Rust toolchain (`cargo`, provided by the flox shell): person and group reads go through personhog with no ORM fallback, so it builds and runs `personhog-replica` + `personhog-router` from `rust/` against the test persons DB.
The first build compiles the crates and can take several minutes; later builds are incremental no-ops.

```bash
# every suite, docker sandboxes, 4 at a time
python -m ee.hogai.eval.sandboxed.harness

# two domains
python -m ee.hogai.eval.sandboxed.harness experiments sql

# one suite, one case
python -m ee.hogai.eval.sandboxed.harness eval_sql --eval churn

# remote sandboxes, every case at once
python -m ee.hogai.eval.sandboxed.harness --provider modal

# print the suite ids and exit
python -m ee.hogai.eval.sandboxed.harness --list
```

| Flag                        | Meaning                                                                          |
| --------------------------- | -------------------------------------------------------------------------------- |
| `--eval <substr>`           | Only run cases whose name contains the substring.                                |
| `--provider {docker,modal}` | Where sandboxes run. Default `docker`.                                           |
| `--max-sandboxes N`         | Cap concurrently live sandboxes across all suites.                               |
| `--agent-model <model>`     | Model the sandboxed agent runs against, pinned for stable cross-run comparison.  |
| `--keep-sandbox-containers` | Skip the end-of-run Docker sweep, to inspect a leftover container. Docker only.  |
| `--rebuild-sandbox-image`   | Force a rebuild of the `posthog-sandbox-base` image before the run. Docker only. |
| `--create-db`               | Rebuild the eval test database instead of reusing it.                            |
| `--case-timeout <seconds>`  | Per-case budget, counted from sandbox acquisition.                               |
| `--trials N`                | Run every case N times (Braintrust trials), for variance on stochastic agents.   |
| `--fail-under <fraction>`   | Exit nonzero when the mean score across all experiments falls below this (0-1).  |
| `--list`                    | Print the discovered suite ids and exit.                                         |

`EXPORT_EVAL_RESULTS=1` appends one JSON summary per experiment to `eval_results.jsonl`.

## Providers

**docker** (default) runs sandboxes as local containers, so a Docker daemon must be reachable.
Each container defaults to 16 GB, so host RAM is what bounds concurrency: the default cap is 4, and raising `--max-sandboxes` needs a big host.

Every docker run verifies the `posthog-sandbox-base` image is fresh before any case starts: it rebuilds when `@posthog/agent` has published a newer version than the one baked into the image, or when the Dockerfile changed since the image was built.
An unchanged image passes the check in under a second, and even a rebuild is mostly layer-cached — only the npm install layer onward re-runs when the agent version moved.
When npm is unreachable the check warns and reuses the existing image instead of failing the run.
`--rebuild-sandbox-image` forces the rebuild regardless.
(The modal DEBUG image is rebuilt by Modal whenever the Dockerfile or build context changes, but a new `@posthog/agent` publish alone does not invalidate it — a known limitation.)

**modal** runs sandboxes remotely.
Modal's network cannot reach `localhost`, so the harness starts ngrok tunnels itself and points the sandbox at the public URLs.
The manual tunnel setup in [`docs/internal/sandboxes-setup-guide.md`](../../../../docs/internal/sandboxes-setup-guide.md) is therefore not needed for evals.
The first modal run pays a one-time remote image build; later runs reuse the cached image until the skills or build context change.

Modal prerequisites, all checked by preflight before anything boots:

- `ngrok` on `PATH`, plus an authtoken (`NGROK_AUTHTOKEN`, or `ngrok config add-authtoken <token>`). Three simultaneous tunnels need a paid ngrok plan; Cloudflare Tunnel is the free alternative.
- Modal credentials: `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`, or a `~/.modal.toml` from `modal token new`.
- `SANDBOX_JWT_PRIVATE_KEY` in the environment. The dev key ships in `.env.example`; the harness auto-loads it from `.env`.

Sandboxes are unbounded by default on modal, meaning every case can hold one at once.
`--max-sandboxes N` is the cost knob.

Each case terminates its own sandbox when it finishes. When the whole run ends, the harness also sweeps the Modal app for its own leftover sandboxes and terminates them, so a crashed or interrupted run doesn't leave sandboxes billing until their TTL.
The sweep is scoped to this run's own tasks (matched by the `task_id` sandbox tag), so a second eval run sharing the same Modal app keeps its sandboxes.

## Concurrency

Every selected suite runs concurrently on one event loop, and a single global semaphore bounds the number of live sandboxes across all of them.
Selecting more suites therefore increases throughput without increasing peak load.

A case holds a sandbox slot only for the window it actually needs one: demo-data copy, setup hook, and the agent run.
Log parsing, Braintrust span building, trace emission, and scoring all happen after the slot is released.
The per-case timeout starts when the slot is acquired, so a case queued behind the semaphore never has its budget eaten by the wait.

## Adding an eval suite

The `/writing-sandboxed-evals` skill ([.agents/skills/writing-sandboxed-evals](../../../../.agents/skills/writing-sandboxed-evals/SKILL.md)) covers the full authoring workflow — cases, seeders, synthesizers, scorer patterns, and verification.
The short version:

There is no registry. Suites are discovered by convention:

1. Create `ee/hogai/eval/sandboxed/<domain>/eval_<name>.py`. The directory becomes the suite's domain.
2. Write one or more coroutines named `eval_*` taking a single `ctx: EvalContext`.
3. Build a list of `SandboxedEvalCase` and hand it to `SandboxedPrivateEval` or `SandboxedPublicEval` along with your scorers and `ctx=ctx`.

```python
from ee.hogai.eval.sandboxed.base import SandboxedPrivateEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.harness.context import EvalContext
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero


async def eval_my_thing(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-my-thing-cli",
        cases=[SandboxedEvalCase(name="my_case", prompt="...")],
        scorers=[ExitCodeZero()],
        ctx=ctx,
    )
```

Bundle related cases into one suite function rather than splitting them across many.
One suite is one Braintrust experiment, which is what makes cross-case comparison and `--eval` filtering useful.

`experiment_name` is the Braintrust experiment key, so changing it starts a fresh history.
Existing suites end in `-cli` because the MCP server serves the `cli` surface; that suffix is kept so history lines up with earlier runs.

Confirm discovery picked your suite up:

```bash
python -m ee.hogai.eval.sandboxed.harness --list | grep my_thing
```

## Output

Progress lines stream as cases finish.
At the end, one table row per experiment shows the case count, per-scorer averages, duration, and the Braintrust URL, followed by the raw-log directories and a traceback for any suite that crashed.
A crashing suite never takes the others down; the run exits non-zero instead.

Raw per-case agent logs land on local disk (`<case>.jsonl`, `<case>.artifacts.json`, `<case>.summary.txt`), which is usually the fastest way to see what the agent actually did.

`SandboxedPrivateEval` runs with `no_send_logs`, so its summary has no Braintrust URL; the local logs are the record.
