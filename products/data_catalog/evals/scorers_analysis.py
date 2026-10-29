"""Scorers for the analysis diligence suite.

The deterministic scorers grade the process from the ordered tool chain: what the agent measured,
which evidence it queried, and in what order. The judges grade the answer, and each one also reads
the rendered chain, so it can tell a verified conclusion from a guess that happens to be right.
Every scorer reads its own ``expected`` entry and self-skips when the case does not set it.
"""

from __future__ import annotations

import re
import json
from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall, is_schema_discovery_call
from products.posthog_ai.eval_harness.scorers import (
    BINARY_CHOICE_SCORES,
    GRADED_ALIGNMENT_CHOICE_SCORES,
    JudgedScorer,
    judge_model,
)
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.posthog_ai.eval_harness.tool_chain import build_tool_chain, render_tool_chain
from products.posthog_ai.evals.experiments.scorers import SurfacesAllFindings

_EXECUTE_SQL = "execute-sql"
_TYPED_QUERY_PREFIX = "query-"
_FIRST_SEEN_PATTERN = re.compile(
    r"\bmin\s*\(\s*(to\w+\s*\()?\s*timestamp|\bargmin\b|order\s+by\s+(\w+\.)?timestamp(?!\s+desc)|\bfirst_seen\b",
    re.IGNORECASE,
)
_ANNOTATION_PATTERN = re.compile(r"\bannotations?\b", re.IGNORECASE)


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    raw_log = (output or {}).get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=(output or {}).get("prompt", "") or "")


def _spec(expected: dict | None, name: str) -> dict[str, Any] | None:
    spec = expected.get(name) if isinstance(expected, dict) else None
    return spec if isinstance(spec, dict) else None


def _call_order(call: ToolCall) -> int:
    return call.sequence if call.sequence is not None else call.position


def _call_text(call: ToolCall) -> str:
    query = call.input.get("query")
    if isinstance(query, str):
        return query
    return json.dumps(call.input, sort_keys=True, default=str)


def _data_calls(parser: LogParser) -> list[ToolCall]:
    """Successful SQL and typed query calls in call order, without information_schema lookups."""
    return sorted(
        (
            call
            for call in parser.get_tool_calls()
            if not call.is_error
            and (call.name == _EXECUTE_SQL or call.name.startswith(_TYPED_QUERY_PREFIX))
            and not is_schema_discovery_call(call)
        ),
        key=_call_order,
    )


class EvidenceQueried(Scorer):
    """Binary: did a successful call query the evidence that tests a hypothesis or a claim?

    ``expected[name]`` holds ``patterns`` (case-insensitive regexes matched against a data call's query)
    and ``tools`` (tool names that count on their own, such as feature flag tools), or either one. One
    class serves several named checks, so a case can grade "measured the claim", "tested the hypothesis",
    and "read the metric definition" separately.
    """

    def __init__(self, *, name: str = "hypothesis_evidence_queried"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        patterns = [re.compile(pattern, re.IGNORECASE) for pattern in spec.get("patterns", [])]
        tools = set(spec.get("tools", []))
        if not patterns and not tools:
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        tool_hits = [call.name for call in parser.get_tool_calls() if not call.is_error and call.name in tools]
        query_hits = [
            _call_text(call)
            for call in _data_calls(parser)
            if any(pattern.search(_call_text(call)) for pattern in patterns)
        ]
        return Score(
            name=self._name(),
            score=1.0 if tool_hits or query_hits else 0.0,
            metadata={"tool_hits": tool_hits, "query_hits": query_hits},
        )


class VerifiedBeforeExplaining(Scorer):
    """Binary: did the agent measure the claimed change before it queried a possible cause?

    ``expected[name]`` holds a ``measure`` regex (a query that measures the claim, such as weekly active
    users over time) and a ``cause`` regex (a query that breaks the change down by a candidate cause,
    such as referrer or browser). A query that matches ``cause`` is a cause query even when it also
    measures. ``score=None`` when no cause query ran, because then there was nothing to explain early.
    """

    def _name(self) -> str:
        return "verified_before_explaining"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        measure, cause = spec.get("measure"), spec.get("cause")
        if not isinstance(measure, str) or not isinstance(cause, str):
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        calls = _data_calls(parser)
        cause_index = next(
            (index for index, call in enumerate(calls) if re.search(cause, _call_text(call), re.IGNORECASE)), None
        )
        if cause_index is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No cause query ran"})
        measured_first = any(re.search(measure, _call_text(call), re.IGNORECASE) for call in calls[:cause_index])
        return Score(
            name=self._name(),
            score=1.0 if measured_first else 0.0,
            metadata={"first_cause_query": _call_text(calls[cause_index]), "data_queries_before": cause_index},
        )


class FirstSeenChecked(Scorer):
    """Binary: did a data query look up when ``expected[name]["subject"]`` first appeared?

    A usage number for a feature that shipped mid-window means little without its start date, so the
    agent must ask for the earliest timestamp (``min(timestamp)``, ``argMin``, or an ascending sort).
    """

    def _name(self) -> str:
        return "first_seen_checked"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        subject = spec.get("subject")
        if not isinstance(subject, str) or not subject:
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        hits = [
            _call_text(call)
            for call in _data_calls(parser)
            if subject.lower() in _call_text(call).lower() and _FIRST_SEEN_PATTERN.search(_call_text(call))
        ]
        return Score(name=self._name(), score=1.0 if hits else 0.0, metadata={"first_seen_queries": hits})


class AnnotationsRead(Scorer):
    """Binary: did the agent read the project's annotations, through a tool or SQL?"""

    def _name(self) -> str:
        return "annotations_read"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if _spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        hits = [
            call.name
            for call in parser.get_tool_calls()
            if not call.is_error
            and (
                "annotation" in call.name
                or (call.name == _EXECUTE_SQL and _ANNOTATION_PATTERN.search(_call_text(call)))
            )
        ]
        return Score(name=self._name(), score=1.0 if hits else 0.0, metadata={"annotation_calls": hits})


_JUDGE_CONTEXT = """\
The user's question:
<question>{{output.prompt}}</question>

The tools the agent called, in order (input -> output, both truncated):
<tool_chain>
{{output.tool_chain}}
</tool_chain>

The agent's final answer:
<final_message>{{output.final_message}}</final_message>"""


class _ChainJudge(JudgedScorer):
    """A judge that reads the question, the ordered tool chain, and the final answer.

    Subclasses set the template and the ``expected`` field they need.
    """

    expected_field: str

    def __init__(self, *, name: str, template: str, choice_scores: dict[str, float], **kwargs: Any):
        super().__init__(
            name=name,
            prompt_template=template.replace("{{context}}", _JUDGE_CONTEXT),
            choice_scores=choice_scores,
            model=judge_model(),
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        if not isinstance(spec.get(self.expected_field), str):
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        final_message = (output or {}).get("last_message")
        if not isinstance(final_message, str) or not final_message.strip():
            return Score(name=self._name(), score=0.0, metadata={"reason": "No final assistant message"})
        return {
            "output": {
                "prompt": (output or {}).get("prompt", ""),
                "final_message": final_message,
                "tool_chain": render_tool_chain(build_tool_chain(output)),
            },
            "expected": spec,
        }


class AnalysisDiligence(_ChainJudge):
    expected_field = "expected_behavior"

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="analysis_diligence",
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            template="""\
You are grading how carefully a data analysis agent worked, not only whether its final number is right.

A diligent analysis:
- checks the user's premise in the data before it explains it,
- tests more than one explanation when the cause is not obvious, and ranks them by evidence,
- flags anomalies, data quality problems, and caveats that change the conclusion,
- states the definitions it used, and
- does not conclude more than its queries show.

{{context}}

What a diligent analysis of this case finds or does:
<expected_behavior>{{expected.expected_behavior}}</expected_behavior>

Grade how well the agent's process and answer match the expected behavior.
Answer with exactly one of:
- perfect: every expected point is present, and the tool chain shows the agent verified it.
- near_perfect: every expected point is present, with a trivial gap in verification or wording.
- slightly_off: the main conclusion is right, but one expected point or one verification step is missing.
- somewhat_misaligned: part of the expected behavior is present, but the conclusion rests on an unverified claim.
- strongly_misaligned: the conclusion is mostly wrong or unverified, with some correct elements.
- useless: the agent accepted a false premise, invented a cause, or did not answer.""",
            **kwargs,
        )


class ContextApplied(_ChainJudge):
    expected_field = "context"

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="context_applied",
            choice_scores=BINARY_CHOICE_SCORES,
            template="""\
You are grading whether a data analysis agent applied one piece of context that changes the answer.

{{context}}

The context the answer must apply:
<context_to_apply>{{expected.context}}</context_to_apply>

Answer yes only if the final answer applies this context: it states the consequence for the number or
adjusts the number. Answer no if the answer ignores the context, mentions it without applying it, or
contradicts it.""",
            **kwargs,
        )


class AnomalyFlagged(_ChainJudge):
    expected_field = "anomaly"

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="anomaly_flagged",
            choice_scores=BINARY_CHOICE_SCORES,
            template="""\
You are grading whether a data analysis agent noticed an anomaly in the data before it gave its answer.

{{context}}

The anomaly a careful analyst flags:
<anomaly>{{expected.anomaly}}</anomaly>

Answer yes only if the final answer names this anomaly and says how it affects the conclusion.
Answer no if the answer presents a result that depends on the anomaly without flagging it.""",
            **kwargs,
        )


class AnswerCorrectness(_ChainJudge):
    expected_field = "expected_answer"

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="answer_correctness",
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            template="""\
You are grading whether a data analysis agent's answer is correct.

{{context}}

The correct answer, in substance:
<expected_answer>{{expected.expected_answer}}</expected_answer>

Answer with exactly one of:
- perfect: the answer matches in substance and states the needed caveats.
- near_perfect: the answer matches in substance, with a trivial gap.
- slightly_off: the main fact is right, but a stated detail is wrong or missing.
- somewhat_misaligned: the answer is partly right.
- strongly_misaligned: the answer is mostly wrong.
- useless: the answer is wrong or missing.""",
            **kwargs,
        )


class SurfacesAllFindingsWhenListed(SurfacesAllFindings):
    """``SurfacesAllFindings`` that skips a case without a findings list.

    The parent scores such a case 1.0, which would lift this suite's average with cases it never graded.
    """

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        if not isinstance(expected, dict) or self._name() not in expected:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        return super()._prepare(output, expected)
