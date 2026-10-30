import json
import uuid
from dataclasses import dataclass
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.notebooks.backend.facade.content import (
    TipTapContent,
    TipTapNode,
    convert_notebook_content_to_markdown,
    create_bullet_list,
    create_heading_with_text,
    create_paragraph_with_content,
    create_paragraph_with_text,
)
from products.product_analytics.backend.facade.models import Insight

_SUMMARY_MARKDOWN = MarkdownIt("commonmark")
_SUMMARY_MARKS = {"strong_open": "bold", "em_open": "italic"}

VERDICT_LABEL = {
    "true_positive": "True positive",
    "false_positive": "False positive",
    "inconclusive": "Inconclusive",
}


@dataclass
class NotebookRenderContext:
    alert: AlertConfiguration
    alert_check: AlertCheck
    insight: Insight
    report: InvestigationReport


def build_investigation_markdown(ctx: NotebookRenderContext) -> str:
    """Render the agent's InvestigationReport into notebook markdown.

    Keeps presentation concerns out of the agent loop. Embedded insight uses the
    SavedInsightNode Query form so the notebook always renders current data.
    """
    content: TipTapContent = []

    content.append(create_heading_with_text(f"Investigation — {ctx.alert.name}", level=1))
    content.append(create_paragraph_with_text(_summary_line(ctx)))

    content.append(create_heading_with_text("Verdict", level=2))
    verdict_text = VERDICT_LABEL.get(ctx.report.verdict, ctx.report.verdict)
    content.append(create_paragraph_with_text(verdict_text))
    content.extend(_summary_content(ctx.report.summary))

    metric_meaning = ctx.report.metric_meaning.strip()
    if metric_meaning:
        content.append(create_heading_with_text("What this metric measures", level=2))
        content.append(create_paragraph_with_text(metric_meaning))

    content.append(create_heading_with_text("Source insight", level=2))
    content.append(_saved_insight_query_node(ctx.insight))

    if ctx.report.hypotheses:
        content.append(create_heading_with_text("Hypotheses", level=2))
        for idx, hypothesis in enumerate(ctx.report.hypotheses, start=1):
            title = hypothesis.title.strip()
            rationale = hypothesis.rationale.strip()
            if not title or not rationale:
                continue
            content.append(create_heading_with_text(f"{idx}. {title}", level=3))
            content.append(create_paragraph_with_text(rationale))
            evidence = [e for e in hypothesis.evidence if e and e.strip()]
            if evidence:
                content.append(create_bullet_list(evidence))

    recommendations = [r for r in ctx.report.recommendations if r and r.strip()]
    if recommendations:
        content.append(create_heading_with_text("Recommendations", level=2))
        content.append(create_bullet_list(recommendations))

    content.append(create_heading_with_text("Run details", level=3))
    content.append(create_paragraph_with_text(_footer_line(ctx)))

    return convert_notebook_content_to_markdown({"type": "doc", "content": content})


def _summary_content(summary: str) -> TipTapContent:
    """Rebuild the agent's Markdown summary as paragraphs and bullet lists with inline marks.

    The summary is model output, so it becomes escaped text with marks. Raw notebook markdown
    could embed components or links.
    """
    content: TipTapContent = []
    items: list[TipTapContent] = []
    list_depth = 0
    for token in _SUMMARY_MARKDOWN.parse(summary):
        if token.type in ("bullet_list_open", "ordered_list_open"):
            list_depth += 1
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
            if list_depth == 0 and items:
                content.append(create_bullet_list(items))
                items = []
        elif token.type == "inline":
            paragraph = create_paragraph_with_content(_inline_content(token.children or []))
            if list_depth:
                items.append([paragraph])
            else:
                content.append(paragraph)
    return content


def _inline_content(children: list[Token]) -> TipTapContent:
    marks: list[str] = []
    nodes: TipTapContent = []
    for child in children:
        if child.type in _SUMMARY_MARKS:
            marks.append(_SUMMARY_MARKS[child.type])
        elif child.type in ("strong_close", "em_close") and marks:
            marks.pop()
        elif child.type in ("text", "html_inline", "code_inline", "softbreak", "hardbreak"):
            text = " " if child.type in ("softbreak", "hardbreak") else child.content
            node_marks = [*marks, "code"] if child.type == "code_inline" else marks
            if text:
                node: dict[str, Any] = {"type": "text", "text": text}
                if node_marks:
                    node["marks"] = [{"type": mark} for mark in node_marks]
                nodes.append(node)
    return nodes


def _summary_line(ctx: NotebookRenderContext) -> str:
    detector_type = (ctx.alert.detector_config or {}).get("type") or "threshold"
    triggered_dates = ctx.alert_check.triggered_dates or []
    window = ""
    if triggered_dates:
        window = f" at {triggered_dates[0]}"
        if len(triggered_dates) > 1:
            window = f" from {triggered_dates[0]} to {triggered_dates[-1]}"
    value = ctx.alert_check.calculated_value
    value_str = f"{value:.4f}" if isinstance(value, (int, float)) else "n/a"
    return (
        f'Detector {detector_type} flagged an anomaly on insight "{ctx.insight.name or ctx.insight.short_id}"'
        f"{window}. Latest value: {value_str}."
    )


def _footer_line(ctx: NotebookRenderContext) -> str:
    return (
        f"Alert check id {ctx.alert_check.id}. "
        f"Tool calls used: {ctx.report.tool_calls_used}. "
        f"Generated automatically — review before acting."
    )


def _saved_insight_query_node(insight: Insight) -> TipTapNode:
    """Embed the insight using a SavedInsightNode reference so the notebook stays live."""
    query = {"kind": "SavedInsightNode", "shortId": insight.short_id}
    return {
        "type": "ph-query",
        "attrs": {
            "title": insight.name or insight.short_id,
            "nodeId": str(uuid.uuid4()),
            "query": json.dumps(query),
        },
    }
