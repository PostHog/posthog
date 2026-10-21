---
name: writing-evals
description: >
  Explains the sandbox harness evals in products/posthog_ai/eval_harness/.
  Covers how to run evals with hogli evals, read scores, compare changes, and write suites, cases, seeders, and scorers.
  Use for sandboxed agent evals, one-shot model evals, and changes under products/posthog_ai/evals/ or products/*/evals/.
  Requires a PostHog repository checkout. Does not cover the customer-facing online evaluation features.
---

# Writing and running evals

An eval measures whether an AI agent or model completes a task correctly.
These evals run against Hedgebox, the generated demo project.
They help check changes to prompts, tools, skills, models, and agent behavior.

The **harness** prepares the services, runs the tasks, collects their output, and applies scorers.
A **suite** groups related cases into one Braintrust experiment.
A **case** contains a user prompt and any expected values or setup function.
A **scorer** measures one requirement and returns a score from 0 to 1, or `None` to skip it.
A **trial** repeats a case to measure variation between model responses.
The harness uses Braintrust as its execution engine, including when it keeps results local.

## Choose what to run

| Suite kind             | What each case runs                                             | Use it to check                                         |
| ---------------------- | --------------------------------------------------------------- | ------------------------------------------------------- |
| Sandboxed, the default | The real coding agent in Docker or Modal, with tools and skills | Task completion, tool use, skill use, and conversations |
| One-shot               | One model task in the harness process                           | A single model response without an agent sandbox        |

Sandboxed cases each get an isolated organization, team, and user copied from the master Hedgebox team.
A seeder can add data to that case's team before the agent starts.
One-shot cases share the master team for read-only queries.
A one-shot task that writes data must copy a team first.

These suites do not run through pytest.
The harness starts shared services once and runs the selected suites concurrently.
Sandboxed suites need the test databases, personhog, demo data, Django, an LLM gateway, MCP, and Temporal.
One-shot suites need only the test databases, personhog, and demo data.
Unit tests for the harness and scorers still use pytest.

## Run an existing case first

Run commands from the repository root in a flox shell.
Use `flox activate -- bash -c "<command>"` if you need to activate flox for one command.
The personhog build needs its Rust toolchain, `pkg-config`, and OpenSSL.

1. Prepare credentials and a provider with [running-evals.md](references/running-evals.md).
2. List suites with `hogli evals --list`. This imports suites but starts no services.
3. Select one suite and one case before a larger run.

```bash
hogli evals sql/eval_sql::eval_sql --eval sql_pageviews_by_browser --max-sandboxes 1 --no-tui
```

The suite selector matches a substring of `<domain>/<module>::<function>`.
`--eval` matches a substring of the case name.
Omitting suite selectors runs every suite, so keep a selector during development.

Docker is the default provider, with a limit of four sandboxes.
Use Modal for larger runs when Modal and Tailscale Funnel access are available.
Modal runs only the agent remotely. Services, data setup, and scoring still run on your machine.
Set `--max-sandboxes` to control parallel execution and cost. Modal has no default limit.

Read [reading-results.md](references/reading-results.md) before deciding whether a run supports a change.
A successful process exit does not prove that the agent met the requirements.
Use `--fail-under <fraction>` when the command must enforce a minimum mean score.

## Add or change a suite

First write the user task and the requirement that a scorer must measure.
Use an existing suite when its cases measure the same behavior.
Use a sandboxed suite when the task needs tools, skills, project state, or several conversation turns.
Use a one-shot suite when one model call can exercise the behavior.

1. Read the [Hedgebox dataset reference](../../../products/posthog_ai/evals/AGENTS.md).
2. Choose an existing suite as a model from [authoring-reference.md](references/authoring-reference.md).
3. Add a case, its expected values, and any required data setup.
4. Reuse a scorer or add a scorer for the requirement.
5. List suites, run the case alone, and inspect its output and scorer metadata.
6. Repeat the affected suite before comparing the change with the base version.

New product-owned suites belong in `products/<product>/evals/eval_<name>.py`.
Built-in agent suites use `products/posthog_ai/evals/<domain>/eval_<name>.py`.
The harness discovers `async def eval_*(ctx: EvalContext) -> None` functions in `eval_*.py` files.
There is no suite registry.
Keep pytest tests outside these suite directories. Do not add a `conftest.py` there.

This complete example checks schema discovery. Save it in a product's `evals/eval_schema_discovery.py`:

```python
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers import RequiredToolCall


async def eval_schema_discovery(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-schema-discovery-cli",
        cases=[
            SandboxedEvalCase(
                name="find_signup_event",
                prompt="Check the project schema. Which event records a user signup?",
            ),
        ],
        scorers=[RequiredToolCall(required={"read-data-schema"})],
        ctx=ctx,
    )
```

Run it with `hogli evals eval_schema_discovery --eval find_signup_event --max-sandboxes 1`.
The scorer checks for a successful schema tool call. It does not check the answer's correctness.
Add a separate answer scorer if correctness is part of the requirement.
The harness adds `ExitCodeZero` automatically. Do not add it to the scorer list.

## Write useful cases and scorers

- Use exact dataset names, such as `signed_up`. Do not guess event or property names.
- Use relative dates and assertions about result structure. Avoid fixed event counts that change when the simulation changes.
- Keep case names unique within a suite. Keep `experiment_name` stable to preserve comparisons with earlier runs.
- Put each scorer's expected values under its `_name()` key. Check existing scorer contracts before choosing the shape.
- Use `setup=` for data that Hedgebox does not supply. Return IDs and expected values through `output["seed"]`.
- Use deterministic checks for observable requirements. Use an LLM judge when the requirement needs semantic judgment.
- Count successful tool calls unless the requirement specifically concerns failed attempts.
- Give missing required output a failed score. Use `None` only when the requirement does not apply.

Read [authoring-reference.md](references/authoring-reference.md) for case fields, multi-turn cases, seeders, scorer patterns, and one-shot suites.
Read the [harness rules](../../../products/posthog_ai/eval_harness/harness/AGENTS.md) before changing the harness itself.

## Choose where results go

| Runner                                        | Braintrust results           | PostHog offline results                    |
| --------------------------------------------- | ---------------------------- | ------------------------------------------ |
| `SandboxedPrivateEval` / `OneShotPrivateEval` | Disabled                     | Disabled by default                        |
| `SandboxedPublicEval` / `OneShotPublicEval`   | Enabled                      | Enabled when `offline_suite` is configured |
| Either runner with `send_to_posthog=True`     | Follows the runner's default | Enabled when `offline_suite` is configured |

Private runners still write local logs and still require the engine's credentials.
`send_to_posthog=False` disables PostHog result uploads independently.
`OPT_OUT_CAPTURE` controls ordinary SDK and trace capture separately from offline result uploads.

For PostHog reporting, register scorer kinds and immutable version UUIDs in the owning `offline_config.py` catalog.
Pass its `offline_suite(...)` configuration to the runner.
List every explicit scorer's `_name()` in `metrics`. The catalog adds `exit_code_zero` for sandboxed suites only.
One-shot configurations also pass `suite_kind=SUITE_KIND`.
See [offline evaluation reporting](../../../docs/internal/ai-offline-evaluation-reporting.md) for credentials, enrollment, and upload limits.

## Check the change

1. Run `hogli evals --list` to check discovery and imports.
2. Run each new or changed case alone. Read its transcript, case summary, and scorer metadata.
3. Check scorer behavior for a correct result, an incorrect result, and missing required output.
4. Run relevant existing scorer or synthesizer tests with `hogli test <path>` when their code changes.
5. Compare repeated runs with the same cases, runtime, model, and skill delivery mode.

Read [reading-results.md](references/reading-results.md) for score limits, repeated trials, and failure diagnosis.
The [harness README](../../../products/posthog_ai/eval_harness/README.md) contains the full command reference.
