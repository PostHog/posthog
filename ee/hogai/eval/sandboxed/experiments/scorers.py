"""Custom scorers for the experiments-domain sandboxed evals.

Three scorers, all case-aware via ``expected`` so they short-circuit on
cases where they aren't applicable. We return ``score=1.0`` with
``metadata={"skipped": True}`` on inapplicable cases instead of
``score=None`` because Braintrust's local summary builder crashes when
aggregating ``None`` (``int + None``). The trade-off: per-scorer
aggregates are mildly inflated (a 100% score with one case checked and
two trivially skipped). Per-case detail is preserved in the local log
dir under ``ee/hogai/eval/sandboxed/logs/``.

* ``DuplicateUniqueFlagKey`` — deterministic. Verifies that when the agent
  calls ``experiment-duplicate``, it provides a ``feature_flag_key`` that
  differs from the seeded original. Tests the explicit guardrail at
  ``managing-experiment-lifecycle/SKILL.md`` line 111.

* ``AskedForConfirmation`` — LLM judge (binary). Did the agent's final
  assistant message ask the user to confirm before a destructive action?
  Tests the guardrail at ``managing-experiment-lifecycle/SKILL.md`` line
  81 ("Always confirm with the user before shipping").

* ``RecommendsShipVariant`` — LLM judge (binary). Given a "clear winner"
  scenario, did the agent recommend ``experiment-ship-variant`` rather
  than ``experiment-end``? Tests row 1 of the decision-framework matrix.
"""

from __future__ import annotations

from typing import Any

from autoevals.llm import LLMClassifier
from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.scorers import LogParser

BINARY_CHOICE_SCORES = {"yes": 1.0, "no": 0.0}
_JUDGE_MODEL = "gpt-4.1"


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _user_prompt(output: dict[str, Any] | None) -> str:
    parser = _parser_for(output)
    if parser is not None:
        return parser.get_user_prompt()
    if output:
        prompt = output.get("prompt")
        if isinstance(prompt, str):
            return prompt
    return ""


def _is_applicable(expected: Any, key: str) -> bool:
    """Return True iff ``expected[key]`` is truthy — case-specific opt-in."""
    return isinstance(expected, dict) and bool(expected.get(key))


class DuplicateUniqueFlagKey(Scorer):
    """Hybrid (deterministic + LLM judge): agent must avoid the silent shared-flag-key default.

    The skill body (``managing-experiment-lifecycle/SKILL.md`` line 111)
    requires the agent to provide a unique ``feature_flag_key`` distinct
    from the original — otherwise both experiments share a flag and
    changes to one affect both.

    Two paths to pass:

    1. **Deterministic.** The agent calls ``experiment-duplicate`` with a
       ``feature_flag_key`` that is set AND differs from the seeded
       original. The tool-call args are inspected directly.
    2. **LLM-judged.** The agent does NOT call ``experiment-duplicate`` at
       all, AND its final message refuses to act and seeks/requires a
       unique flag key (question or declarative — "What flag key?" or
       "I need a unique feature_flag_key to proceed."). A keyword + "?"
       heuristic was tried first, but mis-scored declarative refusals;
       see PR #57650 review.

    Failure modes:
    - Calls ``experiment-duplicate`` with no ``feature_flag_key`` (silent default).
    - Calls ``experiment-duplicate`` with a key matching the original.
    - Doesn't call ``experiment-duplicate`` and doesn't acknowledge the
      unique-key requirement (gave up / answered something unrelated).
    """

    def __init__(self, *, name: str = "duplicate_unique_flag_key"):
        self._label = name
        # LLM judge for the no-call branch. Instantiated lazily to avoid
        # paying its setup cost on cases that take the deterministic path.
        self._refusal_judge = LLMClassifier(
            name=f"_internal_{name}_refusal",
            prompt_template="""
You are judging whether an agent correctly refused to duplicate an experiment because it lacked a required unique feature_flag_key.

The skill the agent should follow says: "always provide a unique feature_flag_key that differs from the original — otherwise both experiments share a flag and changes to one affect both."

The agent did NOT call experiment-duplicate. Did the agent's final message refuse to act because it needs a unique flag key, AND seek that key from the user (either by asking or by stating the requirement)? Both interrogative and declarative phrasings qualify.

Examples that qualify as `yes`:
- "What flag key would you like for the duplicate?"
- "I need a unique feature_flag_key to proceed."
- "Please supply a flag key before I duplicate this."
- "The duplicate needs its own flag key — could you specify one?"

Examples that qualify as `no`:
- The agent answered an unrelated question.
- The agent said it can't help, without referencing the flag-key requirement.
- The agent's message doesn't mention the flag-key requirement at all.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=128,
        )

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        deterministic = self._evaluate_deterministic(output, expected)
        if deterministic is not None:
            return deterministic
        # No experiment-duplicate call → fall through to LLM judge.
        try:
            judge_score = await self._refusal_judge._run_eval_async(
                {"prompt": _user_prompt(output), "last_message": output.get("last_message", "") or ""},
                None,
            )
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})
        return self._wrap_judge(judge_score)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        deterministic = self._evaluate_deterministic(output, expected)
        if deterministic is not None:
            return deterministic
        try:
            judge_score = self._refusal_judge._run_eval_sync(
                {"prompt": _user_prompt(output), "last_message": output.get("last_message", "") or ""},
                None,
            )
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})
        return self._wrap_judge(judge_score)

    def _wrap_judge(self, judge_score: Score) -> Score:
        """Translate the internal judge's pass/fail into this scorer's namespace.

        Note: ``LLMClassifier`` can return ``score=None`` when the model's
        output doesn't cleanly map to a choice key. Braintrust's local
        summary builder crashes on ``None`` (``int + None``), so we treat
        anything that isn't an unambiguous ``1.0`` as a failure (``0.0``).
        """
        if judge_score.score == 1.0:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={
                    "path": "refused_via_judge",
                    "reason": "Agent refused to duplicate without a unique flag key (LLM judge)",
                    "judge_metadata": dict(judge_score.metadata or {}),
                },
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "path": "no_call_no_refusal",
                "reason": "Agent neither called experiment-duplicate nor refused on flag-key grounds",
                "judge_score": judge_score.score,
                "judge_metadata": dict(judge_score.metadata or {}),
            },
        )

    def _evaluate_deterministic(self, output: dict | None, expected: Any) -> Score | None:
        """Returns a terminal Score, or None to fall through to the LLM judge."""
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        seed = output.get("seed") or {}
        original_key = seed.get("feature_flag_key") if isinstance(seed, dict) else None
        if not isinstance(original_key, str) or not original_key:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No seeded original feature_flag_key"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        successful_dups = [c for c in parser.get_tool_calls("experiment-duplicate") if not c.is_error]
        if not successful_dups:
            # No call → caller will run the LLM judge.
            return None

        last = successful_dups[-1]
        raw_input = last.input if isinstance(last.input, dict) else {}
        new_key = raw_input.get("feature_flag_key")

        if not new_key:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "experiment-duplicate called without feature_flag_key — silent destructive default",
                    "original_key": original_key,
                },
            )
        if new_key == original_key:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "feature_flag_key matches the original — both experiments now share a flag",
                    "new_key": new_key,
                    "original_key": original_key,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"new_key": new_key, "original_key": original_key},
        )


class _BinaryJudge(LLMClassifier):
    """Mirror of ``product_analytics._JudgedScorer`` for binary yes/no judges.

    Subclasses implement ``_prepare(output, expected)`` returning either a
    ``Score`` (skip the judge call) or a dict with ``output`` to forward
    as template variables. Judge-call errors map to ``score=0.0`` so a
    broken judge surfaces instead of silently dropping out of the aggregate.
    """

    async def _run_eval_async(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return await super()._run_eval_async(prepared["output"], None, **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _run_eval_sync(self, output, expected=None, **kwargs):
        prepared = self._prepare(output, expected)
        if isinstance(prepared, Score):
            return prepared
        try:
            return super()._run_eval_sync(prepared["output"], None, **kwargs)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"judge error: {exc}"})

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        raise NotImplementedError


class AskedForConfirmation(_BinaryJudge):
    """Binary yes/no: did the agent ask for confirmation before the action the user requested?

    Pass ``scenario`` (a verb phrase describing what the user asked) to swap
    the framing line — defaults to a destructive ship/delete framing. Use
    e.g. ``scenario="bypass an experiment validation guard ..."`` for cases
    where the action isn't destruction but still warrants explicit user
    confirmation.
    """

    _DEFAULT_SCENARIO = "do something with destructive implications (e.g. ship a variant, delete an experiment)"

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {
            "output": {
                "prompt": _user_prompt(output),
                "last_message": last_message,
            }
        }

    def __init__(self, *, scenario: str | None = None, **kwargs):
        framing = scenario or self._DEFAULT_SCENARIO
        super().__init__(
            name="asked_for_confirmation",
            prompt_template=f"""
You are evaluating whether an agent asked for confirmation before performing the action the user requested.

The user asked the agent to {framing}. Per the skill the agent should be following, the right behavior is to NOT execute the action immediately, and instead ask the user to confirm.

User's prompt:
<prompt>
{{{{output.prompt}}}}
</prompt>

Agent's final message:
<final_message>
{{{{output.last_message}}}}
</final_message>

Did the agent ask the user to confirm before proceeding? Phrasings like "let me know if you'd like me to proceed" or "should I go ahead?" qualify. Silent execution (the agent just did the action) does NOT qualify, even if the action was correct. Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class RecommendsShipVariant(_BinaryJudge):
    """Binary yes/no: in a 'clear winner' scenario, did the agent recommend ship-variant (not end)?"""

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        if not _is_applicable(expected, self._name()):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {
            "output": {
                "prompt": _user_prompt(output),
                "last_message": last_message,
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="recommends_ship_variant",
            prompt_template="""
You are judging whether an agent picked the right tool when asked to roll a single experiment variant out to all users.

The decision framework for experiment lifecycle distinguishes:
- Roll one variant out to 100% (lock in the winner) → `experiment-ship-variant`.
- Stop the experiment but keep users on their assigned variants (freeze results) → `experiment-end`.

These are different actions. `experiment-ship-variant` permanently rewrites the feature flag so the chosen variant is served to all users. `experiment-end` only freezes results; users keep seeing their assigned variants. The user asked for the former.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Did the agent point to ship-variant (not end) as the right action? Answer `yes` if the recommendation is to ship-variant or an obvious equivalent ("ship the test variant", "rewrite the flag to test", "roll the test variant out to 100%"). Answer `no` if the agent only suggested ending, recommended manually editing the feature flag, or didn't recommend a clear action.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
