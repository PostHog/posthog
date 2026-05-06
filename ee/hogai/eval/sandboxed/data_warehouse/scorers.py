"""Data-warehouse scorers for the sandboxed agent evals.

The product-analytics scorers grade an agent's *query construction* (was
the right ``query-<insight>`` shape produced?). We're a layer below: did
the HogQL query actually return the right answer?

``HogQLOutputMatches`` looks for the answer in two places — the last
successful ``execute-sql`` tool result, and the agent's final message —
and accepts a small spec language so cases can pin an exact number, a
range, a non-zero floor, or a regex for free-form answers.

Per the convention introduced in #57472, the spec lives under
``expected[scorer_name]``; cases that don't supply one score ``None``
so unrelated cases don't drag the rollup down.
"""

from __future__ import annotations

import re
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import LogParser

EXECUTE_SQL_TOOL_NAME = "execute-sql"

_NUMBER_RE = re.compile(r"-?\d{1,3}(?:[,_]\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
"""Matches integers and decimals, with or without thousands separators.

Deliberately permissive — agents render counts as ``1234``, ``1,234``,
``1_234``, or ``1234.0`` depending on phrasing, and we want a hit on any
of them. The separator-group alternative requires *at least one*
separator (``+`` not ``*``) so plain digits like ``12345`` fall through
to the second alternative and match as a single number rather than
``123`` + ``45``."""


def _parse_number(token: str) -> float | None:
    cleaned = token.replace(",", "").replace("_", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_numbers(text: str) -> list[float]:
    if not text:
        return []
    return [n for n in (_parse_number(m) for m in _NUMBER_RE.findall(text)) if n is not None]


def _parser_for(output: dict | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")


def _last_successful_sql_output(parser: LogParser) -> str:
    """Return the raw text output of the last successful ``execute-sql`` call.

    We pull from the *last* successful call so a recovery case (broken
    query → fixed query) is graded on the fixed query, not the broken one.
    """
    successful = [c for c in parser.get_tool_calls(EXECUTE_SQL_TOOL_NAME) if not c.is_error]
    if not successful:
        return ""
    return successful[-1].output or ""


class HogQLOutputMatches(Scorer):
    """Did the agent's HogQL run actually produce the expected answer?

    Looks at both the last successful ``execute-sql`` tool output and the
    agent's final user-facing message. Passes if either contains a number
    (or text) matching the spec.

    Expected shape (under ``expected[scorer_name]``)::

        {
            # Pick exactly one of:
            "value": 1234,                  # exact numeric match
            "min": 100, "max": 100000,      # range (inclusive on both ends)
            "non_zero": True,               # any number > 0
            "regex": r"\\bdocs\\b",          # text match (case-insensitive)
            # Optional:
            "tolerance": 0.0,               # absolute tolerance for "value"
        }

    Numeric specs check both the SQL output and the last assistant message
    so the agent's prose count is acceptable evidence even if our parse of
    the tool output misses the right column. Regex only checks the
    assistant message, which is where free-form answers live.
    """

    def __init__(self, *, name: str = "hogql_output_matches"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})

        spec = self._spec(expected)
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No spec provided"})

        parser = _parser_for(output)
        sql_output = _last_successful_sql_output(parser) if parser else ""
        last_message = output.get("last_message") or ""

        if "regex" in spec:
            return self._eval_regex(spec["regex"], last_message, sql_output)
        return self._eval_numeric(spec, sql_output, last_message)

    def _spec(self, expected: dict | None) -> dict | None:
        if not isinstance(expected, dict):
            return None
        spec = expected.get(self._name())
        if not isinstance(spec, dict):
            return None
        # At least one mode must be present.
        if not any(k in spec for k in ("value", "min", "max", "non_zero", "regex")):
            return None
        return spec

    def _eval_regex(self, pattern: Any, last_message: str, sql_output: str) -> Score:
        if not isinstance(pattern, str):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "regex must be a string"},
            )
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return Score(name=self._name(), score=None, metadata={"reason": f"invalid regex: {e}"})
        haystack = f"{last_message}\n{sql_output}"
        match = compiled.search(haystack)
        return Score(
            name=self._name(),
            score=1.0 if match else 0.0,
            metadata={
                "pattern": pattern,
                "matched": bool(match),
                "matched_text": match.group(0) if match else None,
            },
        )

    def _eval_numeric(self, spec: dict, sql_output: str, last_message: str) -> Score:
        candidates = _extract_numbers(sql_output) + _extract_numbers(last_message)
        if not candidates:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "No number found in SQL output or final message"},
            )

        # Passing once is enough — agents may quote intermediate numbers,
        # so we accept any candidate that matches the spec.
        for n in candidates:
            if self._matches(n, spec):
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={"matched_number": n, "spec": spec},
                )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "No candidate matched spec",
                "spec": spec,
                "candidates": candidates[:10],
            },
        )

    @staticmethod
    def _matches(n: float, spec: dict) -> bool:
        if "value" in spec:
            tolerance = float(spec.get("tolerance", 0.0))
            return abs(n - float(spec["value"])) <= tolerance
        if "min" in spec or "max" in spec:
            lo = float(spec["min"]) if "min" in spec else float("-inf")
            hi = float(spec["max"]) if "max" in spec else float("inf")
            return lo <= n <= hi
        if spec.get("non_zero"):
            return n > 0
        return False
