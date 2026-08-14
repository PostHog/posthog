// Evidence previews — resolve an `evidence:<kind>/<id>` citation in an agent
// message to a small live summary of the PostHog object it points at. The
// citation carries only the reference; names and status are fetched when the
// preview is shown, so transcripts never embed a stale copy of the data.
//
// The per-kind shaping is kept here (pure, unit-tested) so the client method
// stays a thin "fetch by kind, shape result" dispatch.

import type { Schemas } from "./generated";

export interface EvidencePreview {
  /** The object's name in PostHog. */
  title: string;
  /** One line of status or context, e.g. "Enabled" or "Running since Jan 3". */
  detail?: string;
  /**
   * Canonical id when it differs from the cited one (a feature flag cited by
   * key), so the caller can build the object's web URL.
   */
  resolvedId?: string;
}

function formatDay(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** "pending_release" -> "Pending release". */
function humanizeStatus(status: string): string {
  const words = status.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function shapeInsightPreview(insight: Schemas.Insight): EvidencePreview {
  return {
    title: insight.name || insight.derived_name || insight.short_id,
    detail: insight.description || undefined,
  };
}

export function shapeFlagPreview(flag: Schemas.FeatureFlag): EvidencePreview {
  const state = flag.active ? "Enabled" : "Disabled";
  const name = flag.name?.trim();
  return {
    title: flag.key,
    detail: name ? `${state} · ${name}` : state,
    resolvedId: String(flag.id),
  };
}

export function shapeExperimentPreview(
  experiment: Schemas.Experiment,
): EvidencePreview {
  let detail: string;
  if (experiment.end_date) {
    detail = `Ended ${formatDay(experiment.end_date)}`;
  } else if (experiment.start_date) {
    detail = `Running since ${formatDay(experiment.start_date)}`;
  } else {
    detail = "Draft";
  }
  return { title: experiment.name, detail };
}

export function shapeErrorIssuePreview(
  issue: Schemas.ErrorTrackingIssueFull,
): EvidencePreview {
  const firstSeen = `First seen ${formatDay(issue.first_seen)}`;
  return {
    title: issue.name || "Untitled issue",
    detail: issue.status
      ? `${humanizeStatus(issue.status)} · ${firstSeen}`
      : firstSeen,
  };
}

export function shapeRecordingPreview(
  recording: Schemas.SessionRecording,
): EvidencePreview {
  const person =
    recording.person?.name ||
    recording.person?.distinct_ids?.[0] ||
    recording.distinct_id;
  const duration =
    recording.recording_duration >= 60
      ? `${Math.round(recording.recording_duration / 60)} min`
      : `${Math.round(recording.recording_duration)}s`;
  const parts = [duration];
  if (recording.start_time) parts.push(formatDay(recording.start_time));
  return {
    title: person ? `Session by ${person}` : "Session recording",
    detail: parts.join(" · "),
  };
}

/**
 * Preview of a live `<hogql>` reference: the hover card runs the query and
 * shows its result in one line. `data` is the raw `/query/` response.
 */
export function shapeHogqlPreview(
  data: Record<string, unknown>,
): EvidencePreview | null {
  const results = Array.isArray(data.results) ? data.results : null;
  if (!results) return null;
  const columns = Array.isArray(data.columns) ? data.columns : [];
  const single =
    results.length === 1 && Array.isArray(results[0]) && results[0].length === 1
      ? results[0][0]
      : null;
  if (typeof single === "number" && Number.isFinite(single)) {
    return {
      title: single.toLocaleString("en-US"),
      detail: typeof columns[0] === "string" ? columns[0] : undefined,
    };
  }
  if (typeof single === "string") {
    return { title: single };
  }
  return {
    title: `${results.length.toLocaleString("en-US")} ${results.length === 1 ? "row" : "rows"}`,
    detail:
      columns.filter((c) => typeof c === "string").join(", ") || undefined,
  };
}

export function shapeDashboardPreview(
  dashboard: Schemas.Dashboard,
): EvidencePreview {
  return {
    title: dashboard.name || "Untitled dashboard",
    detail: dashboard.description || undefined,
  };
}

export function shapeCohortPreview(cohort: Schemas.Cohort): EvidencePreview {
  const detail =
    typeof cohort.count === "number"
      ? `${cohort.count.toLocaleString("en-US")} ${cohort.count === 1 ? "person" : "people"}`
      : cohort.description || undefined;
  return { title: cohort.name || "Untitled cohort", detail };
}

export function shapeActionPreview(action: Schemas.Action): EvidencePreview {
  return {
    title: action.name || "Untitled action",
    detail: action.description || undefined,
  };
}

export function shapeSurveyPreview(survey: Schemas.Survey): EvidencePreview {
  let detail: string;
  if (survey.end_date) {
    detail = `Ended ${formatDay(survey.end_date)}`;
  } else if (survey.start_date) {
    detail = `Running since ${formatDay(survey.start_date)}`;
  } else {
    detail = "Draft";
  }
  return { title: survey.name, detail };
}
