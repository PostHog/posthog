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
  /** Short scannable attributes, e.g. "100% rollout" or "42 clicks". */
  facts?: string[];
  /**
   * Canonical id when it differs from the cited one (a feature flag cited by
   * key), so the caller can build the object's web URL.
   */
  resolvedId?: string;
}

function count(n: number, noun: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? noun : `${noun}s`}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

export function shapeFlagPreview(flag: Schemas.FeatureFlag): EvidencePreview {
  const state = flag.active ? "Enabled" : "Disabled";
  const name = flag.name?.trim();

  const facts: string[] = [];
  const filters = isRecord(flag.filters) ? flag.filters : {};
  const groups = Array.isArray(filters.groups) ? filters.groups : [];
  if (groups.length === 1 && isRecord(groups[0])) {
    const rollout = groups[0].rollout_percentage;
    if (typeof rollout === "number") facts.push(`${rollout}% rollout`);
  } else if (groups.length > 1) {
    facts.push(count(groups.length, "release condition"));
  }
  const multivariate = isRecord(filters.multivariate)
    ? filters.multivariate
    : null;
  const variants = Array.isArray(multivariate?.variants)
    ? multivariate.variants.length
    : 0;
  if (variants > 0) facts.push(count(variants, "variant"));
  if (flag.experiment_set?.length) {
    facts.push(`Used by ${count(flag.experiment_set.length, "experiment")}`);
  }

  return {
    title: flag.key,
    detail: name ? `${state} · ${name}` : state,
    facts,
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
  return {
    title: experiment.name,
    detail,
    facts: experiment.feature_flag_key
      ? [`Flag: ${experiment.feature_flag_key}`]
      : undefined,
  };
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

  const facts: string[] = [];
  if (typeof recording.click_count === "number" && recording.click_count > 0) {
    facts.push(count(recording.click_count, "click"));
  }
  if (
    typeof recording.console_error_count === "number" &&
    recording.console_error_count > 0
  ) {
    facts.push(count(recording.console_error_count, "console error"));
  }
  if (recording.start_url) {
    try {
      const url = new URL(recording.start_url);
      facts.push(`${url.host}${url.pathname === "/" ? "" : url.pathname}`);
    } catch {
      // Not a parsable URL; skip the fact rather than show garbage.
    }
  }

  return {
    title: person ? `Session by ${person}` : "Session recording",
    detail: parts.join(" · "),
    facts,
  };
}

export function shapeDashboardPreview(
  dashboard: Schemas.Dashboard,
): EvidencePreview {
  const facts: string[] = [];
  if (Array.isArray(dashboard.tiles)) {
    facts.push(count(dashboard.tiles.length, "tile"));
  }
  if (dashboard.pinned) facts.push("Pinned");
  return {
    title: dashboard.name || "Untitled dashboard",
    detail: dashboard.description || undefined,
    facts,
  };
}

export function shapeCohortPreview(cohort: Schemas.Cohort): EvidencePreview {
  const detail =
    typeof cohort.count === "number"
      ? count(cohort.count, "person").replace("persons", "people")
      : cohort.description || undefined;
  return {
    title: cohort.name || "Untitled cohort",
    detail,
    facts: [cohort.is_static ? "Static" : "Dynamic"],
  };
}

export function shapeActionPreview(action: Schemas.Action): EvidencePreview {
  return {
    title: action.name || "Untitled action",
    detail: action.description || undefined,
    facts: action.steps?.length
      ? [count(action.steps.length, "match step")]
      : undefined,
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
