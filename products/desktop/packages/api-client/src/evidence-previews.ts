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
  /** Mini chart of the object's recent activity, oldest point first. */
  spark?: { points: number[]; render: "line" | "bar" };
  /**
   * Canonical id when it differs from the cited one (a feature flag cited by
   * key, an event cited by name), so the caller can build the object's URL.
   */
  resolvedId?: string;
}

/** Escape a value for interpolation into a single-quoted HogQL string. */
export function hogqlEscape(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

/** 87342 -> "87.3K"; keeps small numbers plain. */
export function compactCount(value: number): string {
  const abs = Math.abs(value);
  const format = (scaled: number, suffix: string): string => {
    const rounded =
      scaled >= 100 ? Math.round(scaled) : Number(scaled.toFixed(1));
    return `${rounded}${suffix}`;
  };
  // Enter each unit where the one below would round up to 1000 (999_999 ->
  // "1000K"), so it promotes to the next unit ("1M") instead of showing a
  // four-digit mantissa.
  if (abs >= 999.5e6) return format(value / 1e9, "B");
  if (abs >= 999.5e3) return format(value / 1e6, "M");
  if (abs >= 1e3) return format(value / 1e3, "K");
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function gridRows(grid: Record<string, unknown>): unknown[][] {
  return (Array.isArray(grid.results) ? grid.results : []).filter(
    (row): row is unknown[] => Array.isArray(row),
  );
}

function cellNumber(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** (day, count) rows -> sparkline points, oldest first. */
export function dailySparkPoints(rows: unknown[][]): number[] {
  return rows.map((row) => cellNumber(row[1]) ?? 0);
}

function count(n: number, noun: string, plural = `${noun}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? noun : plural}`;
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
    const days = Math.max(
      1,
      Math.ceil(
        (Date.now() - new Date(experiment.start_date).getTime()) / 86_400_000,
      ),
    );
    detail = `Running since ${formatDay(experiment.start_date)} · Day ${days}`;
  } else {
    detail = "Draft";
  }

  const facts: string[] = [];
  const parameters: Record<string, unknown> = isRecord(experiment.parameters)
    ? experiment.parameters
    : {};
  const variants = Array.isArray(parameters.feature_flag_variants)
    ? parameters.feature_flag_variants.filter(isRecord)
    : [];
  if (variants.length > 1) {
    const split = variants
      .map((variant) =>
        typeof variant.rollout_percentage === "number"
          ? String(variant.rollout_percentage)
          : "?",
      )
      .join("/");
    facts.push(`${count(variants.length, "variant")} (${split})`);
  }
  if (experiment.feature_flag_key) {
    facts.push(`Flag: ${experiment.feature_flag_key}`);
  }
  const primaryMetric = experiment.saved_metrics?.find(
    (metric) => typeof metric.name === "string" && metric.name,
  );
  if (primaryMetric) facts.push(`Metric: ${primaryMetric.name}`);
  return { title: experiment.name, detail, facts };
}

const EVALUATION_TYPE_LABELS: Record<string, string> = {
  llm_judge: "LLM judge",
  hog: "Hog",
  sentiment: "Sentiment",
};

export function shapeEvaluationPreview(
  evaluation: Schemas.Evaluation,
): EvidencePreview {
  const state = evaluation.enabled ? "Enabled" : "Disabled";
  const reason = evaluation.status_reason?.trim();
  const typeLabel =
    EVALUATION_TYPE_LABELS[String(evaluation.evaluation_type)] ??
    String(evaluation.evaluation_type);
  return {
    title: evaluation.name,
    detail: reason ? `${state} · ${reason}` : state,
    facts: [typeLabel],
  };
}

/** (variant, unique persons) rows -> "control 12.4K · test 12.1K". */
export function exposureFact(rows: unknown[][]): string | null {
  const parts = rows
    .filter((row) => typeof row[0] === "string" && row[0] !== "false")
    .slice(0, 4)
    .map((row) => `${row[0]} ${compactCount(Number(row[1]) || 0)}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/**
 * Fold the status check and 7-day call volume into a flag preview. A stale
 * flag leads with that verdict: PostHog's reason ("rolled out to 100% for 30+
 * days") replaces the name echo because it says what to do about the flag.
 */
export function decorateFlagPreview(
  preview: EvidencePreview,
  status: Schemas.FeatureFlagStatusResponse | null,
  volumeRows: unknown[][],
): EvidencePreview {
  const facts = [...(preview.facts ?? [])];
  let detail = preview.detail;
  if (status?.status?.toLowerCase() === "stale") {
    facts.unshift("Stale");
    if (status.reason) detail = status.reason;
  }
  const points = dailySparkPoints(volumeRows);
  const total = points.reduce((sum, value) => sum + value, 0);
  if (total > 0) facts.push(`${compactCount(total)} calls (7d)`);
  return {
    ...preview,
    detail,
    facts,
    spark: points.length > 1 ? { points, render: "line" } : undefined,
  };
}

/** One-line trace rollup from the aggregate row over its generations. */
export function shapeTracePreview(row: unknown[]): EvidencePreview | null {
  const generations = Number(row?.[0]) || 0;
  if (generations <= 0) return null;
  const facts: string[] = [];
  const cost = Number(row[1]);
  if (Number.isFinite(cost) && cost > 0) facts.push(`$${cost}`);
  const latency = Number(row[2]);
  if (Number.isFinite(latency) && latency > 0) facts.push(`${latency}s`);
  const models = Array.isArray(row[3])
    ? row[3].filter((m): m is string => typeof m === "string" && m !== "")
    : [];
  if (models.length === 1) facts.push(models[0]);
  else if (models.length > 1) facts.push(count(models.length, "model"));
  const errors = Number(row[4]) || 0;
  if (errors > 0) facts.push(count(errors, "error"));
  return { title: count(generations, "generation"), facts };
}

/** Fold `surveys/{id}/stats/` into a survey preview: responses and rate. */
export function decorateSurveyPreview(
  preview: EvidencePreview,
  stats: Record<string, unknown> | null,
): EvidencePreview {
  if (!stats) return preview;
  const facts = [...(preview.facts ?? [])];
  const byEvent = isRecord(stats.stats) ? stats.stats : {};
  const sent = isRecord(byEvent["survey sent"])
    ? Number(byEvent["survey sent"].total_count)
    : Number.NaN;
  if (Number.isFinite(sent)) facts.push(count(sent, "response"));
  const rates = isRecord(stats.rates) ? stats.rates : {};
  const responseRate = Number(rates.response_rate);
  if (Number.isFinite(responseRate) && responseRate > 0) {
    facts.push(`${Math.round(responseRate)}% response rate`);
  }
  return { ...preview, facts };
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
  if (
    typeof recording.active_seconds === "number" &&
    recording.active_seconds >= 60 &&
    recording.active_seconds < recording.recording_duration
  ) {
    facts.push(`${Math.round(recording.active_seconds / 60)} min active`);
  }
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
  // Tile names say what the dashboard covers; the count only says how big.
  const facts: string[] = [];
  const tiles = Array.isArray(dashboard.tiles) ? dashboard.tiles : [];
  const names = tiles
    .map((tile) =>
      isRecord(tile) && isRecord(tile.insight) ? tile.insight.name : null,
    )
    .filter((name): name is string => typeof name === "string" && name !== "");
  if (names.length > 0) {
    const shown = names.slice(0, 3);
    facts.push(...shown);
    // Count from what we showed, not from tiles.length: unnamed tiles are
    // filtered out of names, so a fixed -3 undercounts the remainder.
    const remaining = tiles.length - shown.length;
    if (remaining > 0) facts.push(`+${remaining} more`);
  } else if (Array.isArray(dashboard.tiles)) {
    facts.push(count(tiles.length, "tile"));
  }
  return {
    title: dashboard.name || "Untitled dashboard",
    detail: dashboard.description || undefined,
    facts,
  };
}

export function shapeCohortPreview(cohort: Schemas.Cohort): EvidencePreview {
  const detail =
    typeof cohort.count === "number"
      ? count(cohort.count, "person", "people")
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

export function shapeTicketPreview(ticket: Schemas.Ticket): EvidencePreview {
  const status = ticket.status ? humanizeStatus(ticket.status) : null;
  const priority =
    typeof ticket.priority === "string" && ticket.priority
      ? humanizeStatus(ticket.priority)
      : null;
  const channel = ticket.channel_source
    ? humanizeStatus(String(ticket.channel_source))
    : null;

  const facts: string[] = [];
  const statusLine = [status, priority, channel].filter(Boolean).join(" · ");
  if (statusLine) facts.push(statusLine);
  if (typeof ticket.message_count === "number") {
    const messages = count(ticket.message_count, "message");
    facts.push(
      ticket.last_message_at
        ? `${messages} · last reply ${formatDay(ticket.last_message_at)}`
        : messages,
    );
  }
  const assignedUser = isRecord(ticket.assignee) ? ticket.assignee.user : null;
  if (assignedUser) {
    const name =
      assignedUser.name ||
      [assignedUser.first_name, assignedUser.last_name]
        .filter(Boolean)
        .join(" ") ||
      assignedUser.email;
    if (name) facts.push(`Assigned to ${name}`);
  }

  const snippet = ticket.last_message_text?.trim();
  return {
    title: ticket.email_subject?.trim() || `Ticket #${ticket.ticket_number}`,
    detail: snippet
      ? `“${snippet.length > 120 ? `${snippet.slice(0, 120)}…` : snippet}”`
      : undefined,
    facts,
  };
}

export function shapePersonPreview(
  person: Schemas.PersonRecord,
): EvidencePreview {
  const properties = isRecord(person.properties) ? person.properties : {};
  const email = typeof properties.email === "string" ? properties.email : null;
  const title = person.name?.trim() || email || "Anonymous person";

  const parts: string[] = [];
  if (person.last_seen_at) {
    parts.push(`Last seen ${formatDay(person.last_seen_at)}`);
  }
  if (person.created_at) {
    parts.push(`First seen ${formatDay(person.created_at)}`);
  }
  const facts: string[] = [];
  if (email && email !== title) facts.push(email);
  const country = properties.$geoip_country_name;
  if (typeof country === "string" && country) facts.push(country);
  const browser = properties.$browser;
  if (typeof browser === "string" && browser) facts.push(browser);
  return {
    title,
    detail: parts.join(" · ") || undefined,
    facts,
    resolvedId: person.uuid,
  };
}

export function shapeEventDefinitionPreview(
  definition: Schemas.EventDefinitionRecord,
): EvidencePreview {
  return {
    title: definition.name,
    detail: definition.last_seen_at
      ? `Last seen ${formatDay(definition.last_seen_at)}`
      : undefined,
    resolvedId: definition.id,
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
