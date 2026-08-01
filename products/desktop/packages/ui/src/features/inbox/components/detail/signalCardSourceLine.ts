// ── Source line labels (matching PostHog Cloud's signalCardSourceLine) ────────

const ERROR_TRACKING_TYPE_LABELS: Record<string, string> = {
  issue_created: "New issue",
  issue_reopened: "Issue reopened",
  issue_spiking: "Volume spike",
};

// Turn a scout's skill_name (e.g. "signals-scout-error-tracking") into a
// human-friendly label (e.g. "Error tracking").
function prettifyScoutName(skillName: string): string {
  const cleaned = skillName
    .replace(/^signals-scout-/, "")
    .replace(/[-_]/g, " ")
    .trim();
  if (!cleaned) return "";
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export function signalCardSourceLine(signal: {
  source_product: string;
  source_type: string;
  extra?: Record<string, unknown>;
}): string {
  const { source_product, source_type } = signal;

  if (source_product === "error_tracking") {
    const typeLabel =
      ERROR_TRACKING_TYPE_LABELS[source_type] ?? source_type.replace(/_/g, " ");
    return `Error tracking · ${typeLabel}`;
  }
  if (
    source_product === "session_replay" &&
    source_type === "session_problem"
  ) {
    return "Session replay · Session problem";
  }
  if (
    source_product === "session_replay" &&
    source_type === "session_segment_cluster"
  ) {
    return "Session replay · Session segment cluster";
  }
  if (
    source_product === "session_replay" &&
    source_type === "session_analysis_cluster"
  ) {
    return "Session replay · Session analysis cluster";
  }
  if (source_product === "llm_analytics" && source_type === "evaluation") {
    return "AI observability · Evaluation";
  }
  if (source_product === "zendesk" && source_type === "ticket") {
    return "Zendesk · Ticket";
  }
  if (source_product === "github" && source_type === "issue") {
    return "GitHub · Issue";
  }
  if (source_product === "linear" && source_type === "issue") {
    return "Linear · Issue";
  }
  if (source_product === "pganalyze" && source_type === "issue") {
    return "pganalyze · Issue";
  }
  if (source_product === "health_checks" && source_type === "health_issue") {
    return "Health checks · Issue";
  }
  if (
    source_product === "signals_scout" &&
    source_type === "cross_source_issue"
  ) {
    const skillName =
      typeof signal.extra?.skill_name === "string"
        ? prettifyScoutName(signal.extra.skill_name)
        : "";
    return skillName ? `Scout · ${skillName}` : "Scout · Cross-source issue";
  }

  const productLabel = source_product.replace(/_/g, " ");
  const typeLabel = source_type.replace(/_/g, " ");
  return `${productLabel} · ${typeLabel}`;
}

export function parseExtra(
  raw: Record<string, unknown>,
): Record<string, unknown> {
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return raw;
}
