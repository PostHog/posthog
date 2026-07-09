"""Schema and prompt builder for PostHog Code alert investigations.

Produces:
- ``AlertInvestigationReport`` — the structured output schema the agent must emit.
- ``list_team_investigation_skills`` — returns sorted names of live investigation skills.
- ``build_investigation_prompt`` — constructs the investigation prompt from alert + check context.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.utils import absolute_uri

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.skills.backend.models.skills import LLMSkill

INVESTIGATION_SKILL_PREFIX = "investigation-"
INVESTIGATION_SKILL_CATEGORY = "investigation"


class AlertInvestigationReport(BaseModel):
    """Structured output the investigation agent writes at the end of a run.

    Verdict semantics:
    - ``true_positive``: the breach warrants action — something real broke or regressed.
    - ``false_positive``: the breach is real but expected or benign (seasonality, known
      deploy, test traffic, data pipeline quirk).
    - ``inconclusive``: insufficient evidence to classify confidently.
    """

    findings: str = Field(description="Factual summary of what the agent observed.")
    suspected_cause: str = Field(description="Most likely root cause of the firing.")
    proposed_mitigation: str = Field(description="Concrete next step or fix to address the cause.")
    confidence: float = Field(
        ge=0,
        le=1,
        description="Agent's confidence in the verdict, from 0 (no idea) to 1 (certain).",
    )
    verdict: Literal["true_positive", "false_positive", "inconclusive"] = Field(
        description=(
            "Classification of the alert firing. "
            "'true_positive' = warrants action. "
            "'false_positive' = breach is real but expected or benign "
            "(seasonality, known deploy, test traffic). "
            "'inconclusive' = insufficient evidence to classify."
        )
    )
    pr_url: str | None = Field(
        default=None,
        description="URL of the draft PR opened by the agent, if any.",
    )


def list_team_investigation_skills(team_id: int) -> list[str]:
    """Return sorted names of live ``investigation-*`` LLMSkills for the given team.

    Side-effect: rows whose ``category`` is empty are stamped with
    ``INVESTIGATION_SKILL_CATEGORY`` so future queries can filter by category directly.
    """
    qs = LLMSkill.objects.filter(
        team_id=team_id,
        deleted=False,
        is_latest=True,
        name__startswith=INVESTIGATION_SKILL_PREFIX,
    )
    # Stamp category on rows that haven't been classified yet.
    qs.filter(category="").update(category=INVESTIGATION_SKILL_CATEGORY)
    return sorted(qs.values_list("name", flat=True))


def build_investigation_prompt(
    alert: AlertConfiguration,
    alert_check: AlertCheck,
    *,
    firing_context: dict[str, Any],
    skill_names: list[str],
    previous_task_run_id: str | None,
) -> str:
    """Build the investigation prompt sent to the PostHog Code agent.

    Sections (in order):
    1. Header with alert name and mode detail.
    2. Breach values from ``firing_context``.
    3. Insight and dashboard deep links.
    4. Insight-vs-dashboard-filters caveat.
    5. Baseline skill instruction and team skill listing.
    6. Previous-run section (only on reruns).
    7. Alert owner's instructions (only when ``investigation_context`` is set).
    8. Structured-output closing instruction.
    """
    team_id = alert.team_id
    insight = alert.insight

    # --- Section 1: Header ---
    detector_config = alert.detector_config or {}
    detector_type = detector_config.get("type")
    if detector_type:
        mode_detail = f"**Mode:** Detector-based anomaly detection (type: `{detector_type}`)"
    else:
        threshold_lower = firing_context.get("threshold_lower")
        threshold_upper = firing_context.get("threshold_upper")
        bounds_str = f"lower={threshold_lower}, upper={threshold_upper}"
        mode_detail = f"**Mode:** Threshold-based alert (bounds: {bounds_str})"

    header = f"# Investigate alert firing: {alert.name}\n\n{mode_detail}"

    # --- Section 2: Breach values ---
    alert_check_id = firing_context["alert_check_id"]
    calculated_value = firing_context["calculated_value"]
    threshold_lower = firing_context.get("threshold_lower")
    threshold_upper = firing_context.get("threshold_upper")
    dashboard_ids: list[int] = firing_context.get("dashboard_ids") or []

    breach_lines = [
        "## Breach values",
        f"- **Alert check ID:** `{alert_check_id}`",
        f"- **Calculated value:** {calculated_value}",
    ]
    if threshold_lower is not None:
        breach_lines.append(f"- **Threshold lower:** {threshold_lower}")
    if threshold_upper is not None:
        breach_lines.append(f"- **Threshold upper:** {threshold_upper}")
    breach_section = "\n".join(breach_lines)

    # --- Section 3: Insight and dashboard deep links ---
    insight_url = absolute_uri(f"/project/{team_id}/insights/{insight.short_id}")
    links_lines = [
        "## Data links",
        f"- **Insight** (`{insight.short_id}`): {insight_url}",
    ]
    for d_id in dashboard_ids:
        dashboard_url = absolute_uri(f"/project/{team_id}/dashboard/{d_id}")
        links_lines.append(f"- **Dashboard {d_id}:** {dashboard_url}")
    links_section = "\n".join(links_lines)

    # --- Section 4: Insight-vs-dashboard-filters caveat ---
    caveat_section = (
        "## Important: insight vs dashboard filters\n\n"
        "The breach values above come from the insight's **own configuration** — the query "
        "as stored on the insight itself. An insight can be embedded on several dashboards "
        "(or none), each of which may apply its own date-range or filter overrides. "
        "Numbers visible on a dashboard may therefore legitimately differ from the alerted "
        "value. Treat dashboard views as supporting context, not the canonical breach source."
    )

    # --- Section 5: Skills ---
    skills_lines = [
        "## Investigation skills",
        "Start by invoking the `investigating-alert-firings` skill for the baseline investigation playbook.",
    ]
    if skill_names:
        names_list = ", ".join(f"`{n}`" for n in skill_names)
        skills_lines.append(
            f"This team maintains additional investigation skills in PostHog — read them "
            f"with the skill MCP tools before diving in: {names_list}. "
            "If the alert owner names a specific skill below, prefer it."
        )
    skills_section = "\n\n".join(skills_lines)

    # --- Section 6: Previous-run context (reruns only) ---
    previous_run_section = ""
    if previous_task_run_id:
        previous_run_section = (
            "## Rerun context\n\n"
            f"This is a re-run: the alert is still firing. "
            f"Build on the previous investigation (task run `{previous_task_run_id}`) — "
            "update its draft PR and findings rather than starting cold or opening a duplicate PR."
        )

    # --- Section 7: Alert owner's instructions ---
    owner_instructions_section = ""
    if alert.investigation_context:
        owner_instructions_section = f"## Alert owner's instructions\n\n{alert.investigation_context}"

    # --- Section 8: Structured-output closing instruction ---
    closing_section = (
        "## Structured output\n\n"
        "Finish by setting your structured output to an `AlertInvestigationReport` with: "
        "`findings`, `suspected_cause`, `proposed_mitigation`, `confidence` (0–1), "
        "`verdict` (`true_positive` | `false_positive` | `inconclusive`), and optionally `pr_url`."
    )

    sections = [
        header,
        breach_section,
        links_section,
        caveat_section,
        skills_section,
    ]
    if previous_run_section:
        sections.append(previous_run_section)
    if owner_instructions_section:
        sections.append(owner_instructions_section)
    sections.append(closing_section)

    return "\n\n".join(sections)
