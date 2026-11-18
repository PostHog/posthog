# Sandboxed eval authoring reference

Field-level contracts for eval authors. Paths are relative to `products/posthog_ai/eval_harness/` unless noted.
When anything here disagrees with the code, the code wins — the sources of truth are `config.py`, `base.py`, and `log_parser.py`.

## `SandboxedEvalCase` (`config.py`)

| Field                    | Type                                                   | Meaning                                                                                                                                                   |
| ------------------------ | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                   | `str`                                                  | Case name. Also the `--eval <substr>` filter target and the per-case log filename. Unique within the suite.                                               |
| `prompt`                 | `str`                                                  | The natural-language task given to the agent.                                                                                                             |
| `repo_fixture`           | `str = ""`                                             | Informational only (tracking).                                                                                                                            |
| `expected`               | `dict = {}`                                            | Per-scorer expected values, keyed by each scorer's `_name()`. A scorer reads only its own sub-dict; a missing key means default behavior or self-skip.    |
| `metadata`               | `dict = {}`                                            | Arbitrary tracking/filtering metadata.                                                                                                                    |
| `disable_bundled_skills` | `bool = False`                                         | Clears native skill directories before agent startup. Use when evaluating a separate skill distribution path.                                             |
| `setup`                  | `Callable[[CustomPromptSandboxContext], dict] \| None` | The seed hook. Excluded from serialization (callables don't survive Braintrust's JSON round-trip); the runner re-binds it from the original case by name. |

There is no per-case `skills` attachment field. Skills are built once per run and use native bundled delivery by default. `--skill-delivery exec` enables MCP distribution and clears native skills for every case; `disable_bundled_skills` is an additional per-case override. There is no per-case timeout (`--case-timeout` is run-level, counted from sandbox acquisition).

## Seeder contract

```python
def seed_my_domain(context: CustomPromptSandboxContext) -> dict[str, Any]: ...
```

- Synchronous, plain Django ORM / `sync_execute`; the harness runs it in `asyncio.to_thread`.
- Runs once per case: after the isolated team/user is minted, before the prompt is dispatched.
- `context` is a frozen dataclass; seeders in practice use `context.team_id` and `context.user_id`.
- The return dict becomes `output["seed"]` for every scorer of that case.
- Raising marks the case as an infra error (excluded from averages) rather than scoring 0.

Existing seeders and what they return:

| Seeder                                                  | Returns                                                                                                          |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `seeders/insight.py::seed_insight_noise`                | `{"noise_count", "lookup_insights": [{id, short_id, name}]}`                                                     |
| `seeders/survey.py::seed_survey_feature_flags`          | `{"feature_flags_by_key": {...}}`                                                                                |
| `data_warehouse/seeder.py::seed_warehouse_schema`       | per-needle metadata incl. `queryable` (False when object storage creds are absent — dependent scorers self-skip) |
| `error_tracking/seeders.py::seed_error_tracking_issues` | `{"lookup_issues": [{id, name}]}`                                                                                |
| `experiments/seeders.py::seed_*`                        | seeded experiment ids, flag keys, split signatures                                                               |

`seeders/common.py` provides `make_name_providers(seed)` (seeded mimesis bundle, `DEFAULT_NAME_SEED = 42`) and `LOOKUP_PREFIX = "[lookup]"` — a substring guaranteed absent from generated noise, so a prompt can name a lookup entity unambiguously.

## The `output` dict scorers receive

`AgentArtifacts.model_dump()` (`config.py`) merged with runner extras (`base.py`):

- From `AgentArtifacts`: `exit_code`, `stdout`, `stderr`, `git_diff`, `files_changed`, `test_exit_code`, `test_output`, `lint_exit_code`, `lint_output`, `duration_seconds`, `pr_url`.
- Added by the runner: `last_message` (final assistant text), `messages` (parsed message list), `raw_log` (the raw JSONL — what `LogParser` consumes), `seed` (the setup hook's return dict), `prompt`.

Error semantics: a per-case timeout produces a scored-0 agent failure (`exit_code=1`, stderr says timeout); any other exception (demo copy, seeder, provisioning) re-raises as an errored case excluded from score averages.

## `LogParser` (`log_parser.py`)

- `LogParser.cached(raw_log, initial_prompt="")` — memoized; always use this over the constructor so one case's log is parsed once across scorers.
- `get_tool_calls(name=None) -> list[ToolCall]` — chronological tool calls (excludes the `Skill` tool), optionally filtered by normalized name.
- `get_skill_calls(name=None)` / `was_skill_called(name)` — `Skill` tool invocations (`SkillCall(name, args, call_id, output, is_error, position)`).
- `get_user_prompt()` — first user text, falling back to `initial_prompt`.
- `get_final_agent_message()` — last assistant text block, or `None`.
- `normalize_tool_name(name)` — strips `mcp__<server>__<tool>` down to `<tool>`.
- `INFO_SYNTHETIC_PREFIX = "__info__:"` — synthetic call name unifying `exec {command: "info <tool>"}` and Claude Code's `ToolSearch(select:...)` as "tool schema loaded".

`ToolCall` fields: `name` (normalized; `exec` unwrapped to the inner tool), `input: dict`, `output: str`, `is_error` (also `True` when unpaired), `call_id`, `position` (chronological index), `raw_name`, `is_exec_unwrapped`, `requested_output_format` (`"json"` / `"optimized"` / `None`).

## Judge scorer shape

```python
from typing import Any

from braintrust import Score

from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer


class SaysHello(JudgedScorer):
    def __init__(self, **kwargs):
        super().__init__(
            name="says_hello",
            prompt_template="...did the agent greet the user?...\n<msg>{{output.last_message}}</msg>\nAnswer `yes` or `no`.",
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=128,
            **kwargs,
        )

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not output or not output.get("last_message"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final message"})
        return {"output": {"last_message": output["last_message"]}}
```

`_prepare` returns template variables — `{{output.*}}` / `{{expected.*}}` in `prompt_template` resolve against the returned `"output"` / `"expected"` values, not the raw case output. Shared constants: `BINARY_CHOICE_SCORES` (yes/no), `GRADED_ALIGNMENT_CHOICE_SCORES` (six-bucket scale), `JUDGE_MODEL`.

## Determinism discipline

The dataset is byte-for-byte reproducible under the fixed `EVAL_SEED` (`products/posthog_ai/eval_harness/data_setup.py`), and noise generators use fixed seeds.

- Reference events, properties, flags, and insight names **exactly** as listed in the Hedgebox dataset reference (`products/posthog_ai/evals/AGENTS.md`).
- Prefer relative date ranges (`-30d`, `-8w`, `-6m`) and shape-based assertions; never hard-code absolute counts — they drift when the simulation changes.
- Mirror seeded insights with `filterTestAccounts=True`; use the `account` group type (index 0) for group math.
- Share constants between synthesizer/seeder, prompts, and scorers by importing them (the warehouse needle pattern) instead of restating strings.
