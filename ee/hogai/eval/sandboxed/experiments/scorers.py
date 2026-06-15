"""Custom scorers for the experiments-domain sandboxed evals.

All scorers are case-aware via ``expected`` so they short-circuit on cases
where they aren't applicable. We return ``score=1.0`` with
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

The next three back the ``diagnosing-experiment-results`` skill (groups A–E).

* ``CitesDiagnosticGroup`` — LLM judge (binary). Did the agent's final
  message name the expected diagnostic (uneven-split bias, inactive-flag
  empty-experiment, small-sample noise, test-account-filter divergence,
  ship-variant flag rewrite)? Carries the only judged check on most cases.

* ``SurfacesAllFindings`` — LLM judge (binary). On cases where two
  diagnostics co-occur, did the agent surface BOTH findings rather than
  picking one silently? Tests the anti-bundle rule in ``SKILL.md`` body.

* ``DoesNotRecommendEdit`` — LLM judge (binary). On a stopped experiment,
  did the agent refrain from recommending edits / config changes (which
  cannot be applied)? Tests the state-awareness rule.

* ``AdvisesAgainstShipping`` — LLM judge (binary). On a "should I ship?"
  prompt where the evidence does NOT support a confident ship (small
  sample, guardrail regressing, etc.), did the agent advise against
  shipping or recommend waiting? Behavioral complement to
  ``CitesDiagnosticGroup``: the latter checks "did the agent identify
  the small-sample / guardrail issue", this one checks "did the agent
  actually translate that diagnosis into 'don't ship yet' guidance".

* ``FirstUpdateMetricShape`` — deterministic. Did the agent's *first*
  ``experiment-update`` call carry a correctly shaped metric (per a
  case-supplied validator), rather than discovering the shape via a
  pydantic rejection and retrying? Backs the
  ``configuring-experiment-analytics`` skill's proactive schema guidance.
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


class SharedMetricValidationVerdict(_BinaryJudge):
    """Binary yes/no: agent's verdict aligns with expected AND cites grounded reasons.

    Opts in via ``expected={"shared_metric_validation_verdict": "match" | "mismatch"}``.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        verdict = expected.get(self._name()) if isinstance(expected, dict) else None
        if verdict not in {"match", "mismatch"}:
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        seed = output.get("seed") or {}
        return {
            "output": {
                "prompt": _user_prompt(output),
                "last_message": last_message,
                "expected_verdict": verdict,
                "seeded_event": seed.get("event", "(unknown)"),
                "seeded_metric_type": seed.get("metric_type", "(unknown)"),
                "seeded_math": seed.get("math", "(unknown)"),
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="shared_metric_validation_verdict",
            prompt_template="""
You are judging whether an agent correctly validated a shared (saved) experiment metric against a user's stated acceptance criteria.

Ground truth about the seeded metric:
- event: {{output.seeded_event}}
- metric_type: {{output.seeded_metric_type}}
- math (aggregation): {{output.seeded_math}}
- no filters, no breakdown

Expected verdict for this case: **{{output.expected_verdict}}** (either "match" or "mismatch").

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Score `yes` only if BOTH of the following hold:

1. The agent's verdict aligns with the expected verdict.
   - For "match": the agent must affirm the metric matches the criteria.
   - For "mismatch": the agent must reject the match.
2. The reasons cited by the agent are grounded in the ground truth above (not invented).
   - For "match": the agent should reference the seeded event AND either metric_type or math.
   - For "mismatch": the agent must name at least one specific discrepancy that actually exists between the criteria and the ground truth (e.g. wrong event, wrong math, wrong metric_type). Generic disapproval ("looks off") without naming the discrepancy does NOT qualify.

Score `no` for: hallucinated discrepancies on a match case, vague approval on a mismatch case, asking a clarifying question instead of producing a verdict, or producing a verdict that contradicts the ground truth.

Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class CitesDiagnosticGroup(_BinaryJudge):
    """Binary yes/no: did the agent's final message correctly cite the expected diagnostic?

    Opt-in via ``expected={"diagnosis_group": "<one-line description of the expected diagnosis>"}``.
    The judge compares the final assistant message against the expected description
    and answers yes only if the agent's response identifies that specific
    diagnostic (paraphrasing fine; missing key elements fails).
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        expected_diagnosis = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(expected_diagnosis, str) or not expected_diagnosis.strip():
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
                "expected_diagnosis": expected_diagnosis,
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="diagnosis_group",
            prompt_template="""
You are evaluating whether an agent correctly diagnosed the cause of a problem the user described with their PostHog experiment.

The expected diagnosis for this case (paraphrased) is:
<expected_diagnosis>
{{output.expected_diagnosis}}
</expected_diagnosis>

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` if the agent's final message clearly identifies this diagnostic — the same root cause, in substance, paraphrasing is fine. The agent does not need to use the exact wording from the expected diagnosis, but they must name the same mechanism (e.g. naming "uneven split with multiple-variant exclusion" or equivalent for an A1 case; naming "feature flag is not active so no exposures can fire" for a B0 case; naming "sample size too small, observed difference is likely noise" for a C case; naming "test-account filter" or "default exclusion" causing PostHog to count fewer events than raw SQL for a D case; naming "ship-variant rewrote the flag to 0/100" for an E7 case).

Answer `no` if the agent listed a different diagnostic as the primary cause, if it asked a clarifying question instead of producing a diagnosis, or if it gave a vague "could be many things" answer without anchoring on the expected mechanism.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class SurfacesAllFindings(_BinaryJudge):
    """Binary yes/no: did the agent surface every listed co-occurring finding?

    Opt-in via ``expected={"surfaces_all_findings": ["finding 1", "finding 2", ...]}``.
    Use on cases where multiple diagnostics legitimately co-occur — the skill
    guidance is to surface each finding and let the user pick priority, not to
    bundle silently into a single recommendation.
    """

    def _prepare(self, output, expected) -> dict[str, Any] | Score:
        findings = expected.get(self._name()) if isinstance(expected, dict) else None
        if not isinstance(findings, list) or len(findings) < 2:
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not all(isinstance(f, str) and f.strip() for f in findings):
            return Score(name=self._name(), score=0.0, metadata={"reason": "Malformed findings list"})
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        last_message = output.get("last_message")
        if not isinstance(last_message, str) or not last_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        numbered = "\n".join(f"{i + 1}. {f}" for i, f in enumerate(findings))
        return {
            "output": {
                "prompt": _user_prompt(output),
                "last_message": last_message,
                "findings": numbered,
            }
        }

    def __init__(self, **kwargs):
        super().__init__(
            name="surfaces_all_findings",
            prompt_template="""
You are evaluating whether an agent surfaced every legitimate co-occurring finding rather than picking one and bundling silently. The skill the agent should follow says: "If multiple diagnostics apply, explain each finding and let the user pick the priority. Do not bundle fixes silently."

Expected findings for this case (paraphrased):
<findings>
{{output.findings}}
</findings>

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` only if the agent surfaced every finding in the list above (each one identifiable in substance — paraphrasing is fine). Mentioning extra unrelated diagnostics is acceptable.

Answer `no` if the agent surfaced only some of the findings, bundled them into a single conclusion without distinguishing them, or did not name the substance of one or more findings at all.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class DoesNotRecommendEdit(_BinaryJudge):
    """Binary yes/no: agent led with explanation and didn't push reversal on a stopped experiment.

    Opt-in via ``expected={"does_not_recommend_edit": True}``. On a stopped
    or archived experiment, the desired behavior is to lead with explanation
    of what happened — reversal mechanics may appear in the response, but
    must be strongly qualified ("only do this if you specifically want to…")
    rather than presented as the obvious next step or as an unsolicited
    "want me to revert?" coda. Strict "no reversal at all" enforcement was
    tried across four prose iterations of the skill and never moved the
    agent's behavior — the relaxed grader measures the defensible version
    of the rule (lead with explanation, qualify reversal) rather than the
    absolute version (no reversal ever).
    """

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
            name="does_not_recommend_edit",
            prompt_template="""
You are evaluating an agent's response to a user asking "why did X happen?" about an already-stopped or archived PostHog experiment.

The skill the agent should follow says: "Lead with explanation of what happened. If reversal mechanics are included, they MUST be strongly qualified and MUST NOT be presented as the obvious next step. Unsolicited 'want me to revert?' offers fail the rule."

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` if BOTH of the following hold:

1. **The agent's primary framing is explanation of what happened** — not "here's how to undo it". The bulk of the response describes the mechanism (e.g. ship-variant rewrote the flag, exposure criteria changed, mid-run config drift, etc.), not reversal mechanics.

2. **If reversal mechanics are mentioned at all, they are strongly qualified.** Acceptable phrasings include:
   - "Only do this if you genuinely want to keep splitting traffic post-experiment"
   - "Unless you specifically need X, leave it as-is"
   - "If you didn't intend to ship, you could ... — but understand this discards the experiment's documented decision"
   - A brief mention at the end as a "you can manually edit the flag if needed" caveat, framed as informational rather than prescribed action

Answer `no` if ANY of the following hold:

1. **Reversal is the primary recommendation** or the response leads with how to undo X rather than explaining X.
2. **Reversal is presented as the obvious next step** without a strong intent-conditional qualifier — e.g. a plain "to restore the 50/50 split, edit the flag back" without "only do this if you want to keep splitting traffic" or equivalent caveat.
3. **The agent asks an unsolicited "Want me to revert?" / "Want me to fix this?" question** when the user did not signal reversal intent in their prompt.
4. **Multiple reversal options are listed without qualifier** ("you can: reset the experiment / manually edit the flag / disable the flag") in a way that implies the agent expects the user to act on one.
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


class FirstUpdateMetricShape(Scorer):
    """Deterministic: did the agent's *first* experiment-update call carry a correctly shaped metric?

    Opt-in via ``expected = {"first_update_metric_shape": <validator>}`` where
    ``<validator>`` is a callable ``(metrics: list[dict]) -> tuple[bool, str]``
    returning ``(passed, reason)``. The validator runs against the ``metrics``
    array of the FIRST experiment-update call — successful or failed — so the
    score reflects whether the agent assembled the right payload up-front,
    not whether it eventually recovered after a pydantic validation error.

    Use to assert that proactive schema guidance in a skill prevented the
    "fail, read error, retry" pattern from being the only path to success.
    """

    def _name(self) -> str:
        return "first_update_metric_shape"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: Any) -> Score:
        validator = expected.get(self._name()) if isinstance(expected, dict) else None
        if not callable(validator):
            return Score(
                name=self._name(), score=1.0, metadata={"skipped": True, "reason": "Not applicable to this case"}
            )
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})

        updates = sorted(parser.get_tool_calls("experiment-update"), key=lambda c: c.position)
        if not updates:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Agent never called experiment-update"},
            )

        first = updates[0]
        raw_input = first.input if isinstance(first.input, dict) else {}
        metrics = raw_input.get("metrics") or raw_input.get("metrics_secondary") or []
        if not isinstance(metrics, list) or not metrics:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "First experiment-update had no metrics array", "call_count": len(updates)},
            )

        try:
            passed, reason = validator(metrics)
        except Exception as exc:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"validator error: {exc}"})

        return Score(
            name=self._name(),
            score=1.0 if passed else 0.0,
            metadata={
                "reason": reason,
                "call_count": len(updates),
                "first_call_is_error": first.is_error,
                "first_metric": metrics[0] if metrics else None,
            },
        )


def validate_ratio_revenue_metric(metrics: list[dict]) -> tuple[bool, str]:
    """Ratio metric: numerator must aggregate revenue via math='sum' + math_property='revenue'.

    The is_set-filter-instead-of-aggregation failure mode is caught by the math
    check: a property filter leaves math at its count default.
    """
    ratios = [m for m in metrics if isinstance(m, dict) and m.get("metric_type") == "ratio"]
    if not ratios:
        return (False, f"No ratio metric in payload (saw metric_types: {[m.get('metric_type') for m in metrics]})")
    ratio = ratios[0]
    numerator = ratio.get("numerator")
    if not isinstance(numerator, dict):
        return (False, "Ratio metric missing numerator")
    if numerator.get("math") != "sum":
        return (
            False,
            f"Numerator math is {numerator.get('math')!r}, expected 'sum' (a property filter does not aggregate)",
        )
    if numerator.get("math_property") != "revenue":
        return (False, f"Numerator math_property is {numerator.get('math_property')!r}, expected 'revenue'")
    return (True, "Numerator correctly uses math='sum' + math_property='revenue'")


def validate_retention_metric(metrics: list[dict]) -> tuple[bool, str]:
    """Retention metric: must include retention_window_start and start_handling on the first try."""
    retentions = [m for m in metrics if isinstance(m, dict) and m.get("metric_type") == "retention"]
    if not retentions:
        return (False, f"No retention metric in payload (saw metric_types: {[m.get('metric_type') for m in metrics]})")
    retention = retentions[0]
    missing: list[str] = []
    if "retention_window_start" not in retention:
        missing.append("retention_window_start")
    if "start_handling" not in retention:
        missing.append("start_handling")
    if missing:
        return (False, f"Retention metric missing required fields: {missing}")
    return (True, "Retention metric carries retention_window_start and start_handling")


class AdvisesAgainstShipping(_BinaryJudge):
    """Binary yes/no: did the agent advise against shipping (or recommend waiting)?

    Opt-in via ``expected={"advises_against_shipping": True}``. Behavioral
    complement to ``CitesDiagnosticGroup``: the latter checks whether the agent
    *identified* the relevant diagnostic (small sample, regressing guardrail,
    early significance flip); this scorer checks whether that diagnosis was
    actually translated into "don't ship yet" guidance.

    Use on cases where the evidence does not support a confident ship and the
    user explicitly asks whether to ship. The two failure modes this catches:
    (1) agent identifies the issue but still recommends shipping, and
    (2) agent gives a hedged "could go either way" non-answer that the user
    will read as permission to ship.
    """

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
            name="advises_against_shipping",
            prompt_template="""
You are judging whether an agent gave the user clear "don't ship yet" guidance on a PostHog experiment where the evidence does NOT support a confident ship.

The user is asking some variant of "should I ship?" or "is this a real signal?". The correct answer is to advise AGAINST shipping (or to recommend waiting / gathering more data / holding to control) — not to greenlight a ship and not to hedge into a non-answer the user will read as permission.

User's prompt:
<prompt>
{{output.prompt}}
</prompt>

Agent's final message:
<final_message>
{{output.last_message}}
</final_message>

Answer `yes` if the agent's final message clearly advises against shipping on this evidence. Acceptable phrasings include:
- "Don't ship yet"
- "Wait for more data / a larger sample / the planned duration"
- "Keep control until X is resolved"
- "This isn't a real signal yet — let it run longer"
- "I would not ship the test variant on this evidence"

Answer `no` if ANY of the following hold:
1. The agent recommends shipping the test variant (or any non-control variant).
2. The agent gives a hedged "could go either way / your call" answer without a clear lean against shipping.
3. The agent identifies the diagnostic (small sample, guardrail down) but stops short of saying "don't ship" — leaving the user to draw their own conclusion.
4. The agent only asks clarifying questions without giving the user actionable guidance against shipping.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )
