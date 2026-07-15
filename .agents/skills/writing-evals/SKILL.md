---
name: writing-evals
description: >
  Teaches how to write and run evals on the `products/posthog_ai/eval_harness/` harness — sandboxed agent suites that execute the real coding agent in a Docker or Modal sandbox against a seeded Hedgebox project, and one-shot suites that score a single in-process model invocation per case.
  Use when adding or changing eval suites, cases, scorers, seeders, or synthesizers under `products/posthog_ai/evals/` or `products/*/evals/`, when touching the harness under `products/posthog_ai/eval_harness/`, or when running or debugging those evals (`hogli evals`).
  Covers suite kinds and discovery, case anatomy, the seeder/synthesizer split, the one-branch scorer patterns, and how to read results.
  Not for `ee/hogai/eval/ci/` pytest evals, and not for the LLM Analytics product's evaluation features.
---

# Writing and running evals

The harness under `products/posthog_ai/eval_harness/` runs two kinds of suites: **sandboxed** suites execute the real coding agent inside a real sandbox against a seeded Hedgebox project and score what it did, and **one-shot** suites score a single in-process model invocation per case.
Neither runs under pytest — the standalone harness boots the shared infrastructure the selected suites need (for sandboxed suites: test DB, Django live server, LLM gateway, MCP server, Temporal, personhog; for one-shot suites: just the test DB, personhog, and demo data) and runs every selected suite concurrently, with Braintrust as the eval engine.

Read before writing anything:

- [products/posthog_ai/eval_harness/README.md](../../../products/posthog_ai/eval_harness/README.md) — usage, CLI flags, providers.
- [products/posthog_ai/evals/AGENTS.md](../../../products/posthog_ai/evals/AGENTS.md) — the Hedgebox dataset reference. Your prompts, `expected` values, and scorers must match that taxonomy exactly (`signed_up`, not `sign_up`).
- [products/posthog_ai/eval_harness/harness/AGENTS.md](../../../products/posthog_ai/eval_harness/harness/AGENTS.md) — invariants when touching the harness itself.

Field-level API detail (case fields, the `output` dict, `LogParser`, seeder inventory) lives in [references/authoring-reference.md](references/authoring-reference.md).

## Writing a suite

Suites are discovered by convention, not registered: any coroutine named `eval_*` in a file named `eval_*.py`, taking a single `ctx: EvalContext` and returning `None`.
The harness discovers suites from two root sets:

- `products/posthog_ai/evals/<domain>/` — the built-in tree, reserved for Max and other agent suites. The directory is the domain; the suite id is `<domain>/<module>::<fn>` (import path `products.posthog_ai.evals.<domain>.<module>`).
- `products/<product>/evals/` — where a product ships eval suites next to its own code. Note the **plural** `evals/`: the singular `products/signals/eval/` is an existing pytest tree and is not collected by the harness. The product is the domain; the suite id is `<product>/<module>::<fn>` (import path `products.<product>.evals.<module>`).

New product-owned evals belong under `products/<product>/evals/`. Both root sets use the same conventions (the `eval_*`-coroutine-in-`eval_*.py` rule, the `SUITE_KIND` marker, and substring selectors).
No `evals/` tree needs a pytest-collection exclusion: pytest's default `python_files` matches `test_*.py`, so `eval_*.py` files there are never collected as tests. Do not add a `conftest.py` under an `evals/` tree.

```python
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext


async def eval_my_thing(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-my-thing-cli",
        cases=[SandboxedEvalCase(name="my_case", prompt="...")],
        scorers=[],
        ctx=ctx,
    )
```

- One suite = one Braintrust experiment. Bundle related cases into one suite; split only when the scorecard would be heterogeneous (self-skipping scorers stretch a shared scorer list across mildly different cases, but a scorecard where half the scorers skip half the cases is a sign to split).
- `experiment_name` is the Braintrust history key — renaming it resets cross-run comparison. Existing sandboxed suites end in `-cli` because the MCP server serves the `cli` surface.
- `SandboxedPublicEval` sends logs to Braintrust (summary gets an experiment URL); `SandboxedPrivateEval` runs with `no_send_logs`, so the local log dir is the only record. Use private for cases whose prompts or seeds shouldn't leave the machine.

## One-shot suites

A module-level `SUITE_KIND` declares how a module's suites execute; absent means sandboxed, so existing suites need nothing.
`SuiteKind.ONE_SHOT` suites skip the sandbox entirely: the harness boots only the test DB, personhog, and demo data for them, and preflight requires only `BRAINTRUST_API_KEY` + `LLM_GATEWAY_ANTHROPIC_API_KEY`.

```python
from products.posthog_ai.eval_harness.config import BaseEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.one_shot import OneShotPrivateEval

SUITE_KIND = SuiteKind.ONE_SHOT


async def eval_my_generation(ctx: EvalContext) -> None:
    async def task(case: BaseEvalCase, task_ctx: EvalContext) -> dict:
        return {"answer": ...}  # one model invocation, JSON-serializable

    await OneShotPrivateEval(
        experiment_name="my-generation",
        cases=[BaseEvalCase(name="my_case", prompt="...")],
        scorers=[...],
        task=task,
        ctx=ctx,
    )
```

- The task function runs once per case under the global one-shot limiter with the standard per-case timeout, and its returned dict **is** the scorer `output` — each one-shot suite defines its own output shape, and its scorers read the keys they know about. The runner backfills `prompt`; an optional `last_message` feeds the local `.summary.txt`.
- Cases are `BaseEvalCase` (no `repo_fixture`/`setup`); the shared master Hedgebox team is available as `ctx.demo_data.master_team_id` for read-only queries. A task that needs writes should copy a team via `products.posthog_ai.eval_harness.data_setup.copy_demo_data_to_new_team` under `ctx.demo_slots`.
- The sandbox-log scorer helpers (`LogParser`, `ExitCodeZero`, tool-call scorers) don't apply to one-shot outputs — write deterministic scorers against your own output dict, and reuse `JudgedScorer` for LLM judges.

## Case anatomy

`SandboxedEvalCase` (`products/posthog_ai/eval_harness/config.py`) has five author-facing fields: `name`, `prompt`, `expected`, `metadata`, `setup`.

- `name` doubles as the `--eval <substr>` filter target and the per-case log filename — keep it unique within the suite.
- `expected` is keyed by each scorer's `_name()`. A scorer reads only its own sub-dict and self-skips (or falls back to default behavior) when its key is absent — that is what lets one scorer list span a suite's cases. Judges take payloads like `{"warehouse_answer_correctness": {"expected_answer": "..."}}`.
- Every sandboxed case runs in a fresh isolated org/team/user copied from the master Hedgebox team, so cases never see each other's state. One-shot cases share the master team read-only.

## Seeding data: seeders and synthesizers

When a case needs data Hedgebox doesn't have (a running experiment, error-tracking issues, a warehouse catalog), declare a **seeder** as the case's `setup=`.

The contract:

- Synchronous: `def seed_x(context: CustomPromptSandboxContext) -> dict[str, Any]`. The harness calls it via `asyncio.to_thread` — never make it async.
- Runs once per case, after the per-case team is provisioned and before the agent prompt is dispatched.
- The returned dict lands in scorer `output["seed"]` — this is how scorers learn seeded IDs, flag keys, and expected values. Return everything a scorer will need.
- It receives only the context (`team_id`, `user_id`, ...) — there are no per-case parameters. Case-specific configuration means a dedicated seeder function; adding knobs to a shared seeder silently couples every suite that uses it.
- A seeder exception marks the case as an infra error (excluded from score averages), not a 0 — so a broken seeder never masquerades as an agent regression.

Shared building blocks live in `products/posthog_ai/eval_harness/seeders/` (`common.py` seeded-name providers and the `[lookup]` prefix, `insight.py` noise insights, `survey.py` flags); domain seeders live next to their suites (`data_warehouse/seeder.py`, `error_tracking/seeders.py`, `experiments/seeders.py`).

**Synthesizers** are the generation half of a two-part split, used when the seeded catalog is large or synthetic. A synthesizer is a pure, Django-free, deterministic generator that emits frozen dataclasses — no ORM, no I/O — and the seeder translates that catalog into ORM/ClickHouse/S3 rows inside the case's team.
The split exists so generation stays unit-testable and byte-for-byte reproducible (see `ee/hogai/test/eval/test_warehouse_synthesizer.py`) while installation stays an integration concern.
The reference implementation is `data_warehouse/synthesizer.py`: ~250 realistic noise tables plus seven planted "needles", each targeting one discovery skill, with needle name constants that prompts, `expected` values, and scorers all import verbatim so they can never drift apart.
Follow this split (and the constants-shared-by-all-three pattern) when seeding any new synthetic catalog.

## Writing scorers

Two patterns, each with exactly **one** implemented branch — never both `_run_eval_sync` and `_run_eval_async` (see the Scorers section of `harness/AGENTS.md`):

**Deterministic** — subclass `Scorer`, implement `_run_eval_sync` only. The base class supplies the async path the engine uses.

```python
from products.posthog_ai.eval_harness.log_parser import LogParser
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer


class MyCheck(Scorer):
    def _name(self) -> str:
        return "my_check"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if not output or not output.get("raw_log"):
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
        ...
```

**LLM judge** — subclass `JudgedScorer` from `products.posthog_ai.eval_harness.scorers`, implement `_prepare` only (plus `__init__` with the prompt template). `_prepare` returns either a `Score` to short-circuit without an LLM call, or `{"output": ..., "expected": ...}` template variables (omit `"expected"` for judges that don't need it). The shared base owns the async branch and maps judge errors to `score=0.0`.

Rules that apply to both:

- The harness adds `ExitCodeZero` to every experiment. Do not include it in a suite's `scorers`; an explicit duplicate is rejected.
- Reuse the other generic scorers first: `NoToolCall`, `RequiredToolCall`, and `LastToolCallNot` (all in `products.posthog_ai.eval_harness.scorers`).
- Always parse logs via `LogParser.cached(...)` so a case's log is parsed once, not once per scorer.
- Count only successful tool calls (`is_error=False`) — the agent is free to attempt and fail.
- `score=None` means "skipped": Braintrust omits it from the aggregate entirely. `0.0` means "failed". Pick deliberately — `None` for "this check doesn't apply to this case", `0.0` for "the agent got it wrong" _and_ for broken-judge/missing-input paths that must not silently vanish from the average.

## Running

Read [references/running-evals.md](references/running-evals.md) when setting up the local Docker provider or the remote Modal provider for the first time.
It covers shared credentials, provider authentication, first-run commands, concurrency limits, and common setup failures.
Prefer remote Modal for sandboxed suites when its prerequisites are available.
It runs agent sandboxes in parallel without the local Docker memory ceiling, so multi-case evals finish faster; keep Docker for small smoke tests or when remote access is unavailable.

```bash
hogli evals --list                      # suite ids, no infra
hogli evals eval_my_thing --eval my_case  # one case, docker
hogli evals cli_mcp --provider modal    # a domain, remote, fully parallel
```

`hogli evals:sandboxed` is a back-compat alias of `hogli evals`.

- Run from a flox shell (or wrap in `flox activate -- bash -c "..."`): the personhog build needs flox's Rust toolchain, and outside it the preflight `cargo build` dies on a missing `pkg-config`/OpenSSL.
- Env is loaded automatically (`.env` by the harness, `.env.local`/`.env.development`/`.env.services` by hogli) and a preflight validates the required variables before any infrastructure boots.
- `--provider docker` (default) caps at 4 concurrent sandboxes (16 GB each); `--provider modal` is unbounded — every case runs at once, `--max-sandboxes` is the cost knob.
- Team cloning and case seeding use one setup slot on ordinary local machines and four when `CODER` or `CI` is set.
- `--trials N` repeats every case for variance on stochastic behavior; `--fail-under <fraction>` gates the run's mean score.
- `--agent-runtime codex` runs the OpenAI Codex harness (default model `gpt-5.5`) instead of Claude; it requires `LLM_GATEWAY_OPENAI_API_KEY`. The runtime/model land in the Braintrust experiment metadata, so compare scores within one runtime.
- Every real eval invocation mirrors its complete stdout and stderr to `products/posthog_ai/eval_harness/logs/harness/<timestamp>_<id>.log`. The ending label identifies it as the full run transcript, the last terminal line is its absolute path, and `logs/harness/latest.log` points to the newest transcript. `--list` and argument errors do not create one.
- The plain-text summary is stable for people and agents: only the overall run says `PASS` or `FAIL`; completed suites, experiments, and cases say `DONE`; experiment blocks label scores, URLs, and agent-log directories.
- `EXPORT_EVAL_RESULTS=1` additionally appends one structured Braintrust summary per experiment to `eval_results.jsonl`. It does not replace the always-on transcript.
- Start debugging with the transcript path on the last line. Then open the experiment's `Agent logs` directory for `<case>.jsonl` (raw agent log), `<case>.artifacts.json`, and `<case>.summary.txt`. `logs/runs.jsonl` indexes historical case runs.

## Verification checklist

Before opening a PR:

1. `hogli evals --list` shows your suite (this also import-checks every eval module).
2. Run your new case alone: `hogli evals <suite> --eval <case>`. Read the transcript named on the final line, then the case summary and scorer metadata, not just the score.
3. Unit-test scorer and synthesizer logic where it's cheap — but not inside an `evals/` tree: keep suite dirs free of `conftest.py` and `pytest` imports. Existing homes: `products/posthog_ai/eval_harness/test/` and product test dirs.
4. Prompts and `expected` values use exact Hedgebox taxonomy names, relative date ranges (`-30d`, `-8w`), and shape-based assertions — never absolute counts.
