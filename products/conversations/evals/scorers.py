"""Scorers for the support-reply eval suite.

Deterministic scorers grade outcome, citations, forbidden claims, and cost from the
runner's output dict. LLM judges grade grounding and clarifying-question quality and
self-skip when their `expected` key is absent.
"""

from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.scorers import BINARY_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

OUTCOME_KEY = "outcome_match"
CITATION_KEY = "citation_precision"
FORBIDDEN_KEY = "forbidden_claims"
COST_KEY = "cost"
GROUNDING_KEY = "grounding"
CLARIFY_KEY = "clarifying_question"


def _spec(expected: dict | None, name: str) -> dict | None:
    if not isinstance(expected, dict):
        return None
    spec = expected.get(name)
    return spec if isinstance(spec, dict) else None


def _reply_text(output: dict | None) -> str:
    if not output:
        return ""
    reply = output.get("reply")
    return reply.strip() if isinstance(reply, str) else ""


class OutcomeMatch(Scorer):
    """Did the pipeline land on the fixture's expected eval outcome?"""

    def _name(self) -> str:
        return OUTCOME_KEY

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None or "outcome" not in spec:
            return Score(name=self._name(), score=None, metadata={"reason": "No outcome expectation"})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": (output or {}).get("error", "No output")})
        actual = output.get("eval_outcome")
        want = spec["outcome"]
        return Score(
            name=self._name(),
            score=1.0 if actual == want else 0.0,
            metadata={"expected": want, "actual": actual, "pipeline_result": output.get("pipeline_result")},
        )


class CitationPrecision(Scorer):
    """Of the sources the reply cited, what fraction were in the expected set?

    Skips when the fixture lists no expected sources, so escalate/clarify cases
    that cite nothing (or cite extra) do not drag the precision average.
    """

    def _name(self) -> str:
        return CITATION_KEY

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No citation expectation"})
        want = [name for name in spec.get("source_names") or [] if isinstance(name, str)]
        if not want:
            return Score(name=self._name(), score=None, metadata={"reason": "No expected sources"})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": (output or {}).get("error", "No output")})
        cited = [name for name in (output.get("citation_source_names") or []) if isinstance(name, str)]
        if not cited:
            return Score(name=self._name(), score=0.0, metadata={"expected": want, "cited": cited})
        hits = sum(1 for name in cited if name in want)
        return Score(
            name=self._name(),
            score=hits / len(cited),
            metadata={"expected": want, "cited": cited, "hits": hits},
        )


class ForbiddenClaims(Scorer):
    """Fail if the reply contains a phrase the fixture forbids (case-insensitive)."""

    def _name(self) -> str:
        return FORBIDDEN_KEY

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No forbidden-claim expectation"})
        phrases = [p for p in spec.get("phrases") or [] if isinstance(p, str) and p]
        if not phrases:
            return Score(name=self._name(), score=None, metadata={"reason": "No forbidden phrases"})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": (output or {}).get("error", "No output")})
        reply_lower = _reply_text(output).lower()
        hits = [phrase for phrase in phrases if phrase.lower() in reply_lower]
        return Score(
            name=self._name(),
            score=0.0 if hits else 1.0,
            metadata={"hits": hits},
        )


class CostScorer(Scorer):
    """Require the runner to report sandbox seconds and utility LLM calls."""

    def _name(self) -> str:
        return COST_KEY

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        if _spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No cost expectation"})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": (output or {}).get("error", "No output")})
        raw_cost = output.get("cost")
        cost = raw_cost if isinstance(raw_cost, dict) else {}
        sandbox_seconds = cost.get("sandbox_seconds")
        llm_calls = cost.get("llm_calls")
        present = isinstance(sandbox_seconds, (int, float)) and isinstance(llm_calls, int)
        return Score(
            name=self._name(),
            score=1.0 if present else 0.0,
            metadata={"sandbox_seconds": sandbox_seconds, "llm_calls": llm_calls},
        )


class Grounding(JudgedScorer):
    """Is every factual claim in the reply supported by the provided sources?"""

    def _name(self) -> str:
        return GROUNDING_KEY

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name=GROUNDING_KEY,
            prompt_template="""
You are checking whether a support reply is grounded in the sources it was given.

Customer ticket:
<ticket>
{{output.prompt}}
</ticket>

Reply:
<reply>
{{output.reply}}
</reply>

Sources:
<sources>
{{output.sources}}
</sources>

Is every factual claim in the reply supported by those sources? Hedging, questions, and
acknowledgements do not need a source. Invented product behavior, settings, or limits that
the sources do not state is a failure. Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = _spec(expected, self._name())
        if not spec or not spec.get("required"):
            return Score(name=self._name(), score=None, metadata={"reason": "Grounding not required"})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": (output or {}).get("error", "No output")})
        reply = _reply_text(output)
        if not reply:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No reply to ground"})
        sources = output.get("source_excerpts") or output.get("sources") or []
        return {
            "output": {
                "prompt": output.get("prompt", ""),
                "reply": reply,
                "sources": sources if isinstance(sources, str) else str(sources),
            }
        }


class ClarifyingQuestion(JudgedScorer):
    """Does the agent ask one question that unblocks the answer and is not already in the thread?"""

    def _name(self) -> str:
        return CLARIFY_KEY

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name=CLARIFY_KEY,
            prompt_template="""
You are checking a support agent's clarifying question.

Customer ticket (already in the thread):
<ticket>
{{output.prompt}}
</ticket>

Questions the agent asked:
<questions>
{{output.questions}}
</questions>

Does the agent ask exactly one thing the customer has not already answered, and would
answering it let a later turn reply from the knowledge base? Multiple unrelated asks,
questions already answered in the ticket, or a guess instead of a question are failures.
Answer `yes` or `no`.
""".strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = _spec(expected, self._name())
        if not spec or not spec.get("required"):
            return Score(name=self._name(), score=None, metadata={"reason": "Clarifying question not required"})
        if not output or output.get("error"):
            return Score(name=self._name(), score=0.0, metadata={"reason": (output or {}).get("error", "No output")})
        questions = output.get("clarifying_questions")
        if not isinstance(questions, list):
            questions = []
        cleaned = [q for q in questions if isinstance(q, str) and q.strip()]
        if not cleaned:
            reply = _reply_text(output)
            if "?" in reply:
                cleaned = [reply]
        if not cleaned:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No clarifying question"})
        return {
            "output": {
                "prompt": output.get("prompt", ""),
                "questions": "\n".join(cleaned),
            }
        }


DETERMINISTIC_SCORERS: tuple[Scorer, ...] = (
    OutcomeMatch(),
    CitationPrecision(),
    ForbiddenClaims(),
    CostScorer(),
)

ALL_SCORERS: tuple[Scorer | JudgedScorer, ...] = (
    *DETERMINISTIC_SCORERS,
    Grounding(),
    ClarifyingQuestion(),
)
