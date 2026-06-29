"""Deterministic scorers for the retrieval evals.

Four binary scorers grade the retrieval flow:

* ``SkillLoaded`` — did the agent load the named skill (e.g.
  ``querying-posthog-data``) before producing its answer?
* ``LookupIdInOutput`` — does the agent's final assistant message contain
  the seeded lookup insight's ID, proving it actually queried PostHog
  rather than hallucinating?
* ``InformationSchemaBeforeSql`` — did the agent discover the schema via
  ``system.information_schema.*`` before every ``execute-sql`` that hits a
  ``system.*`` entity table? Catches the failure mode where the agent
  guesses column names on ``system.*`` tables and gets a query that fails
  or silently returns wrong rows. Both the discovery step and the real
  query are ``execute-sql`` calls, so they're told apart by SQL text.
  Mode-agnostic: works for both v2 tools mode and CLI exec mode because
  ``LogParser`` normalizes both to the same tool name and input.
* ``InfoCalledBeforeTool`` — in single-exec CLI mode, did the agent run
  ``info <tool>`` before the first successful ``call <tool>``? Enforces
  the "load schema before invoking" discipline for tools whose
  guidance lives behind ``info`` (e.g. ``execute-sql``). Returns ``None``
  (skipped) outside CLI mode, where tool schemas come bundled with the
  tool registration.

The first two scorers walk ``output["messages"]`` (Anthropic-format) and
``output["seed"]`` (set by the seeder hook in ``base.py:task()``), so
nothing has to be threaded through ``expected``. The third opts in via
``expected = {"information_schema_before_sql": {}}``.
"""

from __future__ import annotations

import re
from typing import Any

from braintrust import Score
from braintrust_core.score import Scorer

from ee.hogai.eval.sandboxed.log_parser import INFO_SYNTHETIC_PREFIX, LogParser

__all__ = ["InfoCalledBeforeTool", "InformationSchemaBeforeSql", "LookupIdInOutput", "SkillLoaded"]


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
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")

        for skill_call in parser.get_skill_calls(self.skill_name):
            if not skill_call.is_error:
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={"matched_via": "skill_tool", "skill": self.skill_name},
                )

        for read_call in parser.get_tool_calls("Read"):
            if read_call.is_error:
                continue
            file_path = read_call.input.get("file_path", "")
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


class InformationSchemaBeforeSql(Scorer):
    """Binary: did the agent discover the schema via ``system.information_schema`` before querying ``system.*``?

    Opt-in via presence of ``expected = {"information_schema_before_sql": {}}``.

    Both the discovery step and the real query are ``execute-sql`` calls, so
    they're distinguished by the SQL text (``input["query"]``):

    * a **discovery** call selects from ``system.information_schema`` (any of
      ``.tables`` / ``.columns`` / ``.relationships`` / ``.data_types``);
    * a **graded** call hits a ``system.*`` entity table (``system.insights``,
      ``system.dashboards``, …) but *not* ``information_schema`` — i.e. an
      actual entity search whose columns must be confirmed first.

    Requires that every graded call was preceded by a successful discovery
    call in the same run. Mode-agnostic — walks all tool calls whether they
    came via tools-mode dispatch or via ``posthog:exec`` unwrapping; the
    ``LogParser`` normalizes both into the same tool name and input.

    Score 1.0 if every graded call was preceded by a successful discovery
    call. 0.0 otherwise (with the offending call IDs in metadata). ``None``
    when no graded call ran — the case didn't exercise the path this scorer
    grades.
    """

    SQL_TOOL = "execute-sql"

    def _name(self) -> str:
        return "information_schema_before_sql"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output, expected)

    @staticmethod
    def _query_text(call) -> str:
        query = call.input.get("query") if isinstance(call.input, dict) else None
        return query.lower() if isinstance(query, str) else ""

    @classmethod
    def _is_discovery(cls, call) -> bool:
        return "information_schema" in cls._query_text(call)

    @classmethod
    def _is_graded(cls, call) -> bool:
        query = cls._query_text(call)
        return "system." in query and "information_schema" not in query

    def _evaluate(self, output: dict | None, expected: dict | None = None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        if not isinstance(expected, dict) or self._name() not in expected:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)

        seen_discovery = False
        offenders: list[str] = []
        graded_calls = 0
        for call in calls:
            if call.is_error or call.name != self.SQL_TOOL:
                continue
            if self._is_discovery(call):
                seen_discovery = True
                continue
            if self._is_graded(call):
                graded_calls += 1
                if not seen_discovery:
                    offenders.append(call.call_id)

        if graded_calls == 0:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "No 'system.*' entity-table query ran"},
            )
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "'system.*' entity query ran without a prior 'system.information_schema' discovery query",
                    "offenders": offenders,
                    "total_calls": graded_calls,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"total_calls": graded_calls},
        )


class InfoCalledBeforeTool(Scorer):
    """Binary: did the agent call ``info <tool>`` before the first successful ``call <tool>``?

    CLI-mode-specific. In single-exec mode the agent must learn each tool's
    schema by running ``exec {command: "info <tool>"}`` before invoking it
    via ``exec {command: "call <tool> <json>"}``. The ``LogParser`` unwraps
    both shapes; ``info`` becomes the synthetic name
    ``__info__:<tool>``. This scorer ensures every successful call to
    ``<tool>`` was preceded by a successful ``info <tool>`` in the same run.

    Returns ``None`` (skipped) when:
    * the run is not CLI mode (no ``exec``-unwrapped tool calls), or
    * the target tool was never called.

    Returns ``1.0`` if every successful call was preceded by ``info``,
    ``0.0`` otherwise (with offending call IDs in metadata).
    """

    def __init__(self, tool_name: str, *, name: str | None = None):
        self.tool_name = tool_name
        self._label = name or f"info_before_{tool_name.replace('-', '_')}"

    def _name(self) -> str:
        return self._label

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output: dict | None) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser(raw_log, initial_prompt=output.get("prompt", "") or "")
        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)

        if not any(call.is_exec_unwrapped for call in calls):
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": "Not single-exec CLI mode (no exec-unwrapped calls)"},
            )

        info_synthetic = f"{INFO_SYNTHETIC_PREFIX}{self.tool_name}"
        seen_info = False
        offenders: list[str] = []
        successful_calls = 0
        for call in calls:
            if call.is_error:
                continue
            if call.name == info_synthetic:
                seen_info = True
                continue
            if call.name == self.tool_name:
                successful_calls += 1
                if not seen_info:
                    offenders.append(call.call_id)

        if successful_calls == 0:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"'{self.tool_name}' was never called successfully"},
            )
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": f"'{self.tool_name}' called without a prior successful 'info {self.tool_name}'",
                    "offenders": offenders,
                    "total_calls": successful_calls,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"total_calls": successful_calls},
        )
