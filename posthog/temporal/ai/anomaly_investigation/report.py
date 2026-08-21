import re
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

_LEADING_PARAMETER_TAG_RE = re.compile(r'^\s*<parameter\s+name="([^"]*)">\s*')


def _close_truncated_json(fragment: str) -> str | None:
    """Append the closing brackets a truncated JSON array/object fragment is missing.

    Sonnet 5 sometimes stops emitting a leaked-string list argument before closing the
    outer array, so `[{...}` arrives with no final `]`. Scanning bracket nesting (string
    literals excluded) tells us exactly which closers to append. Fragments cut off inside
    a string literal are not repairable this way, and balanced fragments need no repair;
    both return None so the caller falls through to its next strategy.
    """
    closers: list[str] = []
    in_string = False
    escaped = False
    for ch in fragment:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "[":
            closers.append("]")
        elif ch == "{":
            closers.append("}")
        elif ch in "]}":
            if not closers or closers[-1] != ch:
                return None
            closers.pop()
    if in_string or not closers:
        return None
    return fragment.rstrip().rstrip(",") + "".join(reversed(closers))


def _parse_leaked_value(field: str, value: str) -> tuple[str | None, Any]:
    """Parse a list argument the model emitted as a string.

    Returns (leaked_tag_name, parsed). Sonnet 5's text-tool-call syntax leaks in several
    shapes seen in production: a stray `<parameter name="...">` tag prefixing the JSON
    array, sibling parameters concatenated after the array into the same string value
    (`[...], "recommendations": [...]`), and arrays cut off before their closing bracket.
    The leaked tag name matters to the caller: a tag that names a different field (e.g.
    `evidence` inside `hypotheses`) means the content belongs elsewhere.
    """
    tag: str | None = None
    body = value
    match = _LEADING_PARAMETER_TAG_RE.match(value)
    if match:
        tag = match.group(1)
        body = value[match.end() :]
    start = body.find("[")
    if start == -1:
        return tag, None
    fragment = body[start:].strip()
    # Concatenated sibling parameters become valid JSON once wrapped in an object keyed
    # by this field. A plain well-formed array also parses through this path; unwrap it
    # back to the bare list so the caller's leaked-tag handling still applies.
    try:
        wrapped = json.loads(f'{{"{field}": {fragment}}}')
        if set(wrapped) == {field}:
            return tag, wrapped[field]
        return tag, wrapped
    except ValueError:
        pass
    end = fragment.rfind("]")
    if end != -1:
        try:
            return tag, json.loads(fragment[: end + 1])
        except ValueError:
            pass
    repaired = _close_truncated_json(fragment)
    if repaired is not None:
        try:
            return tag, json.loads(repaired)
        except ValueError:
            pass
    return tag, None


def _normalize_report_args(data: dict[str, Any]) -> dict[str, Any]:
    """Undo the argument manglings Sonnet 5 produces when submitting the report.

    Handles the shapes observed in production traces: list fields serialized as strings
    (with or without leaked `<parameter>` tags, truncation, or concatenated siblings),
    and a single hypothesis flattened into top-level `title`/`rationale`/`evidence` keys.
    Unrecoverable values pass through unchanged so pydantic raises its normal validation
    error instead of this masking the problem.
    """
    data = dict(data)
    stray_evidence: list[Any] | None = None
    for field in ("hypotheses", "recommendations"):
        value = data.get(field)
        if not isinstance(value, str):
            continue
        tag, parsed = _parse_leaked_value(field, value)
        if isinstance(parsed, dict):
            for key, item in parsed.items():
                if key == field or key not in data:
                    data[key] = item
        elif isinstance(parsed, list):
            if field == "hypotheses" and tag == "evidence":
                # The string was one hypothesis's evidence array; its title/rationale sit
                # flattened at the top level and are re-attached below.
                stray_evidence = parsed
                del data[field]
            else:
                data[field] = parsed
    hypotheses = data.get("hypotheses")
    hypotheses_usable = isinstance(hypotheses, list) and any(isinstance(item, dict) for item in hypotheses)
    if not hypotheses_usable and ("title" in data or "rationale" in data):
        hypothesis: dict[str, Any] = {
            "title": str(data.get("title") or "Hypothesis"),
            "rationale": str(data.get("rationale") or ""),
        }
        evidence = stray_evidence if stray_evidence is not None else data.get("evidence")
        if isinstance(evidence, list):
            hypothesis["evidence"] = [str(item) for item in evidence]
        data["hypotheses"] = [hypothesis]
    return data


class InvestigationHypothesis(BaseModel):
    """A single hypothesis proposed by the agent, with supporting evidence."""

    title: str = Field(description="Short name of the hypothesis, e.g. 'Bot traffic spike'.")
    rationale: str = Field(description="Why the agent thinks this hypothesis explains the anomaly.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Bullet points of concrete evidence. Keep each line short and factual.",
    )


class InvestigationReport(BaseModel):
    """Structured output the agent emits as its final message. Rendered into a Notebook."""

    verdict: Literal["true_positive", "false_positive", "inconclusive"] = Field(
        description=(
            "Agent's validation call on the alert firing. Use 'true_positive' when the anomaly "
            "is real and business-relevant, 'false_positive' when it's a data/release artifact "
            "or noise that shouldn't have fired, or 'inconclusive' when there isn't enough "
            "evidence to decide."
        ),
    )
    metric_meaning: str = Field(
        default="",
        description=(
            "One sentence, read off the metric definition in the context: what the alerted number "
            "counts — the event, the aggregation, and the filters that scope it. Write this before "
            "reasoning about causes, and never infer it from the insight's name."
        ),
    )
    summary: str = Field(description="1-3 sentence plain-English summary of what happened.")
    hypotheses: list[InvestigationHypothesis] = Field(
        default_factory=list,
        description="Ordered by likelihood; top 2-3 hypotheses.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Suggested next actions for the on-call engineer or product owner.",
    )
    tool_calls_used: int = Field(default=0, description="Number of tool calls the agent made, for audit.")

    @model_validator(mode="before")
    @classmethod
    def _recover_mangled_args(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return _normalize_report_args(data)


def salvage_report(args: Any) -> InvestigationReport | None:
    """Build a report from whichever fields survive validation.

    Last resort when the model's final report call fails full validation even after
    recovery. Verdict and summary are the load-bearing fields (the verdict gates
    notification dispatch and the summary is what users read in the alert), so keeping
    them with degraded hypotheses beats collapsing the whole run to a generic
    inconclusive fallback. Returns None when verdict or summary themselves are invalid.
    """
    if not isinstance(args, dict):
        return None
    data = _normalize_report_args(args)
    try:
        report = InvestigationReport.model_validate({"verdict": data.get("verdict"), "summary": data.get("summary")})
    except ValidationError:
        return None
    if not report.summary.strip():
        # A verdict with no explanation must not gate notification dispatch; the
        # inconclusive fallback is safer than an unexplained suppression.
        return None
    hypotheses = data.get("hypotheses")
    if isinstance(hypotheses, list):
        for item in hypotheses:
            try:
                report.hypotheses.append(InvestigationHypothesis.model_validate(item))
            except ValidationError:
                continue
    recommendations = data.get("recommendations")
    if isinstance(recommendations, list):
        report.recommendations = [item for item in recommendations if isinstance(item, str)]
    metric_meaning = data.get("metric_meaning")
    if isinstance(metric_meaning, str):
        report.metric_meaning = metric_meaning
    return report
