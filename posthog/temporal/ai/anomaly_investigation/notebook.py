import json
import uuid
from dataclasses import dataclass
from typing import Any

from posthog.models import Insight
from posthog.models.alert import AlertCheck, AlertConfiguration
from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport

from products.notebooks.backend.util import (
    TipTapContent,
    TipTapNode,
    create_bullet_list,
    create_empty_paragraph,
    create_heading_with_text,
    create_paragraph_with_text,
)

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


def build_investigation_notebook(ctx: NotebookRenderContext) -> dict[str, Any]:
    """Render the agent's InvestigationReport into a TipTap document.

    Keeps presentation concerns out of the agent loop. Embedded insight uses the
    SavedInsightNode ph-query form so the notebook always renders current data.
    """
    content: TipTapContent = []

    content.append(create_heading_with_text(f"Investigation — {ctx.alert.name}", level=1))
    content.append(create_paragraph_with_text(_summary_line(ctx)))
    content.append(create_empty_paragraph())

    content.append(create_heading_with_text("Verdict", level=2))
    verdict_text = VERDICT_LABEL.get(ctx.report.verdict, ctx.report.verdict)
    content.append(create_paragraph_with_text(f"{verdict_text} — {ctx.report.summary}"))
    content.append(create_empty_paragraph())

    content.append(create_heading_with_text("Source insight", level=2))
    content.append(_saved_insight_query_node(ctx.insight))
    content.append(create_empty_paragraph())

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
            content.append(create_empty_paragraph())

    recommendations = [r for r in ctx.report.recommendations if r and r.strip()]
    if recommendations:
        content.append(create_heading_with_text("Recommendations", level=2))
        content.append(create_bullet_list(recommendations))
        content.append(create_empty_paragraph())

    content.append(create_heading_with_text("Run details", level=3, collapsed=True))
    content.append(create_paragraph_with_text(_footer_line(ctx)))

    return {"type": "doc", "content": content}


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
            "height": None,
            "title": insight.name or insight.short_id,
            "nodeId": str(uuid.uuid4()),
            "query": json.dumps(query),
        },
    }
