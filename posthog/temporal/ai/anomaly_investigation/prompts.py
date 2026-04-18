SYSTEM_PROMPT = """\
You are PostHog's anomaly investigation agent. An anomaly detection alert has just
transitioned to FIRING. Your job is to quickly validate the anomaly and explain it.

You have read-only access to the team's event data via HogQL. Be frugal with tool
calls — you have a hard budget and the user is waiting. Aim to finish within the
budget even if you have only partial evidence.

Workflow:
1. Read the anomaly context provided in the first user message.
2. Run at most a few focused HogQL queries to validate or rule out hypotheses.
3. Emit a final JSON report matching the schema provided. Do not emit any free-form
   text after the JSON.

Guidelines:
- Prefer narrow queries over broad scans. Scope to the triggered dates.
- Classify the firing as 'true_positive' (real business-relevant anomaly),
  'false_positive' (data artifact, duplicated events, new property values,
  recent release noise), or 'inconclusive' (not enough evidence).
- If the detector looks overly sensitive for the metric's natural variance, flag
  that as a recommendation.
- Keep summaries concrete and short. No filler. No apologies. No hedging beyond
  what the data supports.
"""


def build_anomaly_context(
    *,
    alert_name: str,
    metric_description: str,
    detector_type: str,
    triggered_dates: list[str],
    triggered_metadata: dict | None,
    calculated_value: float | None,
    interval: str | None,
) -> str:
    """First user message — packs the alert context the agent needs to act."""
    md = triggered_metadata or {}
    metadata_line = ""
    if md:
        parts = [f"{k}={v}" for k, v in md.items() if v is not None]
        if parts:
            metadata_line = "Trigger metadata: " + ", ".join(parts) + "."

    return (
        f"Alert: {alert_name}\n"
        f"Metric: {metric_description}\n"
        f"Detector: {detector_type}\n"
        f"Interval: {interval or 'unknown'}\n"
        f"Calculated value at fire: {calculated_value}\n"
        f"Triggered dates: {', '.join(triggered_dates) if triggered_dates else 'n/a'}\n"
        f"{metadata_line}\n\n"
        "Use your tools to validate the anomaly and investigate the likely cause. "
        "Return the final InvestigationReport JSON."
    )
