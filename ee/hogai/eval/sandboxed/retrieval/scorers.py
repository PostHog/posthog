"""Deterministic scorers for the insight-retrieval eval.

Two binary scorers grade the retrieval flow:

* ``SkillLoaded`` — did the agent load the named skill (e.g.
  ``querying-posthog-data``) before producing its answer?
* ``LookupIdInOutput`` — does the agent's final assistant message contain
  the seeded lookup insight's ID, proving it actually queried PostHog
  rather than hallucinating?

Both scorers walk ``output["messages"]`` (Anthropic-format) and
``output["seed"]`` (set by the seeder hook in ``base.py:task()``), so
nothing has to be threaded through ``expected``.
"""

from __future__ import annotations

import re
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.scorers import iter_successful_tool_calls, normalize_tool_name

__all__ = ["SkillLoaded", "LookupIdInOutput"]


_SKILL_TOOL_NAMES = frozenset({"Skill"})


class SkillLoaded(Scorer):
    """Binary: did the agent load a specific Claude Code skill?

    Recognized as either:
    * a successful ``Skill`` tool call (``input.skill == skill_name``), or
    * a successful ``Read`` tool call whose ``file_path`` references the
      skill's ``SKILL.md`` (catches the fallback path where the agent
      reads the skill file directly).
    """

    def __init__(self, skill_name: str, *, name: str | None = None):
        self.skill_name = skill_name
        self._label = name or "skill_loaded"

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        messages = output.get("messages")
        if not messages:
            return Score(name=self._name(), score=None, metadata={"reason": "No parsed messages"})

        for tool_use, _ in iter_successful_tool_calls(messages):
            normalized = normalize_tool_name(tool_use.get("name"))
            tool_input = tool_use.get("input") or {}
            if not isinstance(tool_input, dict):
                continue

            if normalized in _SKILL_TOOL_NAMES:
                if tool_input.get("skill") == self.skill_name:
                    return Score(
                        name=self._name(),
                        score=1.0,
                        metadata={"matched_via": "skill_tool", "skill": self.skill_name},
                    )

            if normalized == "Read":
                file_path = tool_input.get("file_path", "")
                if isinstance(file_path, str) and self._matches_skill_file(file_path):
                    return Score(
                        name=self._name(),
                        score=1.0,
                        metadata={"matched_via": "read_skill_md", "file_path": file_path},
                    )

        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": f"Skill '{self.skill_name}' was never loaded"},
        )

    def _matches_skill_file(self, file_path: str) -> bool:
        """Heuristic match: a Read of `<...>/<skill_name>/SKILL.md` counts as load.

        The sandbox bind-mounts the local skills directory, so the exact path
        depends on how skills are laid out in the cache — guard with a
        substring check on both the skill name and the SKILL.md filename.
        """
        return self.skill_name in file_path and file_path.endswith("SKILL.md")


_NORMALIZE_RE = re.compile(r"[^a-z0-9 ]+")


def _normalize(value: str) -> str:
    return _NORMALIZE_RE.sub(" ", value.lower())


class LookupIdInOutput(Scorer):
    """Binary: does the agent's final message contain the expected lookup ID?

    Resolves the expected lookup in two ways, in order:

    1. ``expected.lookup_id_in_output.lookup_name`` — explicit override
       used by fuzzy cases where the prompt describes the insight in
       natural language (e.g. "MAUs") rather than naming it verbatim.
    2. Substring match: the lookup whose seeded ``name`` appears
       (normalized) in the prompt. Used by literal-name cases.

    Then checks whether the matching insight's ``id`` (as a decimal string)
    or ``short_id`` appears in ``last_message``.

    Returns ``score=None`` (rather than ``0.0``) when there's no usable
    seed payload or no resolvable lookup — that's a misconfigured case,
    not a model failure.
    """

    def __init__(self, *, name: str = "lookup_id_in_output"):
        self._label = name

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})

        seed = output.get("seed") or {}
        lookups = seed.get("lookup_insights") if isinstance(seed, dict) else None
        if not isinstance(lookups, list) or not lookups:
            return Score(name=self._name(), score=None, metadata={"reason": "No seed.lookup_insights on output"})

        expected_lookup = self._resolve_from_expected(expected, lookups)
        resolution = "expected_override" if expected_lookup is not None else None

        if expected_lookup is None:
            prompt = self._extract_prompt(output)
            if not prompt:
                return Score(name=self._name(), score=None, metadata={"reason": "No user prompt available"})
            prompt_norm = _normalize(prompt)
            for lookup in lookups:
                if not isinstance(lookup, dict):
                    continue
                name = lookup.get("name")
                if isinstance(name, str) and _normalize(name) in prompt_norm:
                    expected_lookup = lookup
                    resolution = "prompt_substring"
                    break

        if expected_lookup is None:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No expected lookup configured for this case"},
            )

        last_message = output.get("last_message") or ""
        if not isinstance(last_message, str):
            last_message = str(last_message)

        expected_id = str(expected_lookup.get("id", ""))
        expected_short_id = expected_lookup.get("short_id") or ""

        matched_via: str | None = None
        if expected_id and expected_id in last_message:
            matched_via = "id"
        elif expected_short_id and expected_short_id in last_message:
            matched_via = "short_id"

        if matched_via is None:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "Expected lookup ID not present in last assistant message",
                    "expected_id": expected_id,
                    "expected_short_id": expected_short_id,
                    "expected_name": expected_lookup.get("name"),
                    "resolution": resolution,
                },
            )

        return Score(
            name=self._name(),
            score=1.0,
            metadata={
                "matched_via": matched_via,
                "expected_id": expected_id,
                "expected_short_id": expected_short_id,
                "expected_name": expected_lookup.get("name"),
                "resolution": resolution,
            },
        )

    def _resolve_from_expected(self, expected: dict | None, lookups: list[Any]) -> dict[str, Any] | None:
        """Honor an explicit ``lookup_name`` override on the case's ``expected``.

        Accepts either ``expected[<scorer name>].lookup_name`` or the static
        key ``expected.lookup_id_in_output.lookup_name`` so a case author
        doesn't have to know the scorer instance's renamed label.
        """
        if not isinstance(expected, dict):
            return None
        spec = expected.get(self._name()) or expected.get("lookup_id_in_output")
        if not isinstance(spec, dict):
            return None
        target = spec.get("lookup_name")
        if not isinstance(target, str) or not target:
            return None
        target_norm = _normalize(target)
        for lookup in lookups:
            if not isinstance(lookup, dict):
                continue
            name = lookup.get("name")
            if isinstance(name, str) and _normalize(name) == target_norm:
                return lookup
        return None

    @staticmethod
    def _extract_prompt(output: dict[str, Any]) -> str:
        """Recover the original user prompt — same shape as the product-analytics scorers use."""
        for key in ("prompt", "input"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
        messages = output.get("messages") or []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if isinstance(text, str) and text:
                            return text
        return ""
