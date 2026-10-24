# Authoring reference

Use this reference to add cases, data setup, or scorers.
Paths in the tables are relative to `products/posthog_ai/` unless they name another product.
The source contracts are [config.py](../../../../products/posthog_ai/eval_harness/config.py), [base.py](../../../../products/posthog_ai/eval_harness/base.py), and [log_parser.py](../../../../products/posthog_ai/eval_harness/log_parser.py).

## Choose an existing example

| Requirement                         | Example                                                                    |
| ----------------------------------- | -------------------------------------------------------------------------- |
| Query generation and answer checks  | `evals/sql/eval_sql.py` and `evals/sql/scorers.py`                         |
| Tool selection and rendering        | `evals/cli_mcp/eval_render_ui.py` and `evals/cli_mcp/scorers.py`           |
| Data setup with a generated catalog | `evals/data_warehouse/seeder.py` and `evals/data_warehouse/synthesizer.py` |
| Several turns in one agent session  | `evals/product_analytics/eval_typed_runner_lock_in.py`                     |
| A surface-specific system prompt    | `products/slack_app/evals/eval_posthog_first.py`                           |

Keep related cases in one suite when they use a common set of scorers.
Split a suite when most scorers would skip most cases.
The suite function receives `EvalContext`. Pass that context to the runner as `ctx=ctx`.

## Case fields

`SandboxedEvalCase` inherits the common fields from `BaseEvalCase`.

| Field                    | Purpose                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------- |
| `name`                   | Unique case name within the suite; target for the `--eval` substring filter           |
| `prompt`                 | First user message                                                                    |
| `followups`              | Later user messages in the same sandboxed agent session; defaults to an empty list    |
| `expected`               | Expected values for scorers; defaults to an empty dictionary                          |
| `metadata`               | Tracking values; defaults to an empty dictionary                                      |
| `repo_fixture`           | Informational fixture name; does not install a repository                             |
| `disable_bundled_skills` | Remove native skills for this case; defaults to `False`                               |
| `interaction_origin`     | Select a surface's system prompt, such as `"slack"`; defaults to `None`               |
| `setup`                  | Optional synchronous seeder function; the runner restores it after case serialization |

Use the scorer's `_name()` as the key for expected values.
For example, a judge can read `{"warehouse_answer_correctness": {"expected_answer": "..."}}`.
A missing key can mean a default or a skipped check. Read the scorer before omitting its key.

There is no per-case skill attachment or timeout field.
The harness builds product skills from the checkout once per run.
`--skill-delivery bundled` uses native skills by default.
`--skill-delivery exec` enables MCP skill distribution and removes native skills from every sandbox.
Compare these delivery modes in separate runs because MCP configuration applies to the whole process.

For a multi-turn module, set `MULTI_TURN_CASES = True` at module level.
The harness uses this marker to increase the default case budget.
Set `followups=[...]` on each case that needs later user messages.
The runner sends each message after the preceding turn completes and keeps the same session.
Follow-up messages share one case deadline.
One-shot runners ignore `followups`.

## Add data with a seeder

A seeder installs data in the case's isolated team before the agent receives the prompt.
Use it when Hedgebox does not contain the flags, experiments, errors, or warehouse data that the task needs.

The function has this signature:

```python
def seed_my_domain(context: CustomPromptSandboxContext) -> dict[str, Any]: ...
```

Import `CustomPromptSandboxContext` from `products.tasks.backend.facade.agents`.
Pass the function as `setup=seed_my_domain`, without calling it.
The harness calls it through `asyncio.to_thread`, so keep it synchronous.
Use `context.team_id` and `context.user_id` for the isolated case.
The function receives no extra case parameters. Use a separate function when a case needs different setup.

Return the IDs, keys, and reference values that scorers need.
The runner puts this dictionary in `output["seed"]`.
A seeder exception produces an infrastructure error, separate from a failed agent score.

Shared helpers live in `eval_harness/seeders/`:

| Helper                                 | Purpose                                                                      |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `common.py::make_name_providers`       | Generate repeatable names from a fixed seed                                  |
| `common.py::LOOKUP_PREFIX`             | Mark target entities with `[lookup]`, which generated noise does not contain |
| `insight.py::seed_insight_noise`       | Add unrelated insights and target insights                                   |
| `survey.py::seed_survey_feature_flags` | Add flags that survey cases need                                             |

Product-specific seeders live beside their suites.
Read the seeder's return value before using `output["seed"]` in a scorer.

For a large generated catalog, separate generation from installation:

1. A **synthesizer** generates repeatable data without Django, database access, or other I/O.
2. It returns frozen data objects.
3. A seeder installs those objects in the case's databases or object storage.

Use the warehouse synthesizer and seeder as the example.
Import shared target-name constants into prompts, expected values, and scorers to prevent differences between them.
Use fixed seeds for generated noise.

## Output available to sandboxed scorers

The runner combines `AgentArtifacts` with the agent log and setup results.

| Output key                                                       | Content                                                |
| ---------------------------------------------------------------- | ------------------------------------------------------ |
| `exit_code`, `stderr`                                            | Execution status and error text                        |
| `last_message`, `messages`, `prompt`                             | Final answer, parsed messages, and initial user prompt |
| `raw_log`                                                        | Raw JSONL agent log for `LogParser`                    |
| `seed`                                                           | Seeder return value                                    |
| `stdout`, `tool_call_count`, `duration_seconds`                  | Tool output, tool count, and elapsed time              |
| `git_diff`, `files_changed`, `pr_url`                            | Available repository artifacts                         |
| `test_exit_code`, `test_output`, `lint_exit_code`, `lint_output` | Available test and lint artifacts                      |

Some fields can be empty or `None`. Check the required fields before scoring.
One-shot tasks define their own output dictionary. Do not assume they contain sandboxed output fields.

## Write a deterministic scorer

Reuse `RequiredToolCall`, `NoToolCall`, and other generic scorers when they measure the requirement.
A new deterministic scorer subclasses `Scorer` and implements `_run_eval_sync` only.
The base class provides the async execution path.

This example checks final text for a required event name:

```python
from typing import Any

from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer


class MentionsEvent(Scorer):
    def _name(self) -> str:
        return "mentions_event"

    def _run_eval_sync(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        target = (expected or {}).get(self._name())
        if target is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Not applicable"})
        message = (output or {}).get("last_message") or ""
        return Score(
            name=self._name(),
            score=1.0 if target["event"] in message else 0.0,
            metadata={"event": target["event"]},
        )
```

Use it with `expected={"mentions_event": {"event": "signed_up"}}` and `scorers=[MentionsEvent()]`.
This scorer checks only text presence. It cannot prove that the answer is correct.
Use a query-result check or a judge when the requirement needs more evidence.
A missing answer fails the check. A case without this expected-value key skips it.

## Parse tool and skill calls

Use `LogParser.cached(raw_log, initial_prompt=...)` so scorers share one parsed log.

| Method                       | Result                                                        |
| ---------------------------- | ------------------------------------------------------------- |
| `get_tool_calls(name=None)`  | Chronological tool calls, excluding the native `Skill` tool   |
| `get_skill_calls(name=None)` | Native skill calls                                            |
| `was_skill_called(name)`     | Whether the native skill call exists                          |
| `get_user_prompt()`          | First user text, with the supplied initial prompt as fallback |
| `get_final_agent_message()`  | Last assistant text block, or `None`                          |
| `normalize_tool_name(name)`  | Tool name without the `mcp__<server>__` prefix                |

Tool calls expose `name`, `input`, `output`, `is_error`, `call_id`, and `position`.
The parser unwraps exec calls to the inner tool name.
Unpaired calls have `is_error=True`.
Use `not call.is_error` when counting successful actions.
The synthetic `__info__:` prefix identifies schema-discovery calls.
For exec skill delivery, reuse the existing skill-distribution scorers rather than assuming a native `Skill` call.

## Write an LLM judge

Subclass `JudgedScorer` from `products.posthog_ai.eval_harness.scorers`.
Set the prompt template and choice scores in `__init__`. Implement `_prepare` only.
Do not implement `_run_eval_sync` or `_run_eval_async` on the judge.

`_prepare` returns either a `Score` or template variables such as `{"output": ..., "expected": ...}`.
The template reads these prepared values through `{{output.*}}` and `{{expected.*}}`.
Return a failed score when required input is missing.
Return `None` as the score only when the check does not apply.
The shared judge base maps judge errors to `0.0`.

Reuse `JUDGE_MODEL`, `BINARY_CHOICE_SCORES`, or `GRADED_ALIGNMENT_CHOICE_SCORES` where appropriate.
Read an existing domain judge before writing a new judge prompt.

## Write a one-shot suite

Set `SUITE_KIND = SuiteKind.ONE_SHOT` at module level.
Import `SuiteKind` from `products.posthog_ai.eval_harness.harness.requirements`.
Use `BaseEvalCase` and `OneShotPrivateEval` or `OneShotPublicEval` from `eval_harness.one_shot`.

Supply `task=` with an async function that accepts `(case: BaseEvalCase, ctx: EvalContext)` and returns a JSON-serializable dictionary.
That dictionary becomes the scorer's `output`. The runner adds `prompt` if needed.
An optional `last_message` supplies text for the local summary.
The harness applies its one-shot concurrency limit and case timeout.

Read the shared demo team through `ctx.demo_data.master_team_id`.
If the task needs writes, call `data_setup.copy_demo_data_to_new_team` under `ctx.demo_slots`.
Use deterministic scorers for your dictionary or `JudgedScorer` for semantic checks.
Do not add `ExitCodeZero` or sandbox-log scorers. One-shot suites have no agent sandbox log.

## Keep expectations stable

Read the [Hedgebox taxonomy](../../../../products/posthog_ai/evals/AGENTS.md) before writing prompts and assertions.
Use relative date ranges such as `-30d`, `-8w`, or `-6m`.
Use `filterTestAccounts=True` when matching seeded insights.
Use the `account` group type, at index 0, for group calculations.
Keep scorer and synthesizer unit tests in `eval_harness/test/` or the product's existing test directory.
