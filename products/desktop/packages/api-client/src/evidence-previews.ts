// Evidence previews — resolve an `evidence:<kind>/<id>` citation in an agent
// message to a small live summary of the PostHog object it points at. The
// citation carries only the reference; names and status are fetched when the
// preview is shown, so transcripts never embed a stale copy of the data.
//
// The per-kind shaping is kept here (pure, unit-tested) so the client method
// stays a thin "fetch by kind, shape result" dispatch.

import type { Schemas } from "./generated";

export interface EvidenceDetailField {
  label: string;
  value: string;
}

export interface EvidenceDetailSection {
  title: string;
  fields: EvidenceDetailField[];
}

export interface EvidencePreview {
  /** The object's name in PostHog. */
  title: string;
  /** One line of status or context, e.g. "Enabled" or "Running since Jan 3". */
  detail?: string;
  /** Short scannable attributes, e.g. "100% rollout" or "42 clicks". */
  facts?: string[];
  /** Mini chart of the object's recent activity, oldest point first. */
  spark?: { points: number[]; render: "line" | "bar" };
  sections?: EvidenceDetailSection[];
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

function detailSection(
  title: string,
  fields: Array<[string, string | null | undefined]>,
): EvidenceDetailSection[] {
  const present = fields.flatMap(([label, value]) =>
    value ? [{ label, value }] : [],
  );
  return present.length > 0 ? [{ title, fields: present }] : [];
}

function stringValue(value: unknown): string | null {
  if (typeof value === "string" && value) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return null;
}

function conciseValue(value: unknown): string | null {
  const valueAsString = stringValue(value);
  if (valueAsString) return valueAsString.slice(0, 120);
  if (Array.isArray(value)) return value.map(String).join(", ").slice(0, 120);
  return null;
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

function actionStepSummary(step: unknown): string | null {
  if (!isRecord(step)) return null;
  const terms = [
    ["Event", conciseValue(step.event)],
    ["URL", conciseValue(step.url)],
    ["Selector", conciseValue(step.selector)],
    ["Text", conciseValue(step.text)],
    ["Link", conciseValue(step.href)],
  ].flatMap(([label, value]) => (value ? [`${label}: ${value}`] : []));
  const properties = Array.isArray(step.properties)
    ? step.properties.length
    : 0;
  if (properties > 0) terms.push(count(properties, "property"));
  return terms.length > 0 ? terms.join(" · ") : null;
}

function flagConditionSummary(group: unknown): string | null {
  if (!isRecord(group)) return null;
  const properties = Array.isArray(group.properties)
    ? group.properties
        .flatMap((property) => {
          if (!isRecord(property)) return [];
          const key = conciseValue(property.key);
          const operator = conciseValue(property.operator) ?? "equals";
          const value = conciseValue(property.value);
          return key && value ? [`${key} ${operator} ${value}`] : [];
        })
        .join(", ")
    : "";
  const rollout =
    typeof group.rollout_percentage === "number"
      ? `${group.rollout_percentage}% rollout`
      : null;
  const variant = conciseValue(group.variant);
  const summary = [properties, rollout, variant ? `Variant: ${variant}` : null]
    .filter(Boolean)
    .join(" · ");
  return summary || null;
}

function surveyQuestionSummary(question: unknown): string | null {
  if (!isRecord(question)) return null;
  const prompt = conciseValue(question.question);
  const type = conciseValue(question.type);
  if (!prompt) return type;
  return type ? `${prompt} (${humanizeStatus(type)})` : prompt;
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
  const isMultivariate = multivariate !== null;
  const variants = Array.isArray(multivariate?.variants)
    ? multivariate.variants.length
    : 0;
  if (variants > 0) facts.push(count(variants, "variant"));
  if (flag.experiment_set?.length) {
    facts.push(`Used by ${count(flag.experiment_set.length, "experiment")}`);
  }

  const flagType = flag.is_remote_configuration
    ? "Remote config"
    : isMultivariate
      ? "Multivariate"
      : "Boolean";
  return {
    title: flag.key,
    detail: name ? `${state} · ${name}` : state,
    facts,
    sections: [
      ...detailSection("Configuration", [
        ["State", state],
        ["Type", flagType],
        [
          "Release conditions",
          groups.length ? count(groups.length, "condition") : "All users",
        ],
        ["Evaluation runtime", stringValue(flag.evaluation_runtime)],
        [
          "Experience continuity",
          flag.ensure_experience_continuity === null ||
          flag.ensure_experience_continuity === undefined
            ? null
            : flag.ensure_experience_continuity
              ? "Enabled"
              : "Disabled",
        ],
        [
          "Last called",
          flag.last_called_at ? formatDay(flag.last_called_at) : null,
        ],
      ]),
      ...detailSection(
        "Release conditions",
        groups.map((group, index) => [
          `Set ${index + 1}`,
          flagConditionSummary(group),
        ]),
      ),
    ],
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
  const variantSplit =
    variants.length > 1
      ? variants
          .map((variant) =>
            typeof variant.rollout_percentage === "number"
              ? String(variant.rollout_percentage)
              : "?",
          )
          .join("/")
      : null;
  if (variantSplit) {
    facts.push(`${count(variants.length, "variant")} (${variantSplit})`);
  }
  if (experiment.feature_flag_key) {
    facts.push(`Flag: ${experiment.feature_flag_key}`);
  }
  const primaryMetric = experiment.saved_metrics?.find(
    (metric) => typeof metric.name === "string" && metric.name,
  );
  if (primaryMetric) facts.push(`Metric: ${primaryMetric.name}`);
  const outcome =
    typeof experiment.conclusion === "string" && experiment.conclusion
      ? humanizeStatus(experiment.conclusion)
      : null;
  return {
    title: experiment.name,
    detail,
    facts,
    sections: [
      ...detailSection("Configuration", [
        ["Feature flag", experiment.feature_flag_key],
        ["Variants", variantSplit],
        ["Primary metric", primaryMetric?.name ?? null],
        ["Conclusion", outcome],
        [
          "Created",
          experiment.created_at ? formatDay(experiment.created_at) : null,
        ],
      ]),
      ...detailSection(
        "Variants",
        variants.map((variant, index) => [
          conciseValue(variant.key) ?? `Variant ${index + 1}`,
          typeof variant.rollout_percentage === "number"
            ? `${variant.rollout_percentage}% rollout`
            : null,
        ]),
      ),
    ],
  };
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
  const modelConfiguration = (evaluation as unknown as Record<string, unknown>)
    .model_configuration;
  const model = isRecord(modelConfiguration)
    ? stringValue(modelConfiguration.model)
    : null;
  const conditions = Array.isArray(evaluation.conditions)
    ? evaluation.conditions.length
    : 0;
  return {
    title: evaluation.name,
    detail: reason ? `${state} · ${reason}` : state,
    facts: [typeLabel],
    sections: [
      ...detailSection("Configuration", [
        ["State", state],
        ["Method", typeLabel],
        ["Model", model],
        [
          "Trigger conditions",
          conditions ? count(conditions, "condition") : "All matching data",
        ],
        [
          "Updated",
          evaluation.updated_at ? formatDay(evaluation.updated_at) : null,
        ],
      ]),
      ...detailSection(
        "Trigger conditions",
        (Array.isArray(evaluation.conditions) ? evaluation.conditions : []).map(
          (condition, index) => [
            `Condition ${index + 1}`,
            flagConditionSummary(condition),
          ],
        ),
      ),
    ],
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
    sections: [
      ...(preview.sections ?? []),
      ...detailSection("Activity", [
        ["Calls in 7 days", total > 0 ? compactCount(total) : null],
        ["Staleness", status?.status ? humanizeStatus(status.status) : null],
      ]),
    ],
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
  return {
    title: count(generations, "generation"),
    facts,
    sections: detailSection("Trace", [
      ["Generations", count(generations, "generation")],
      ["Cost", Number.isFinite(cost) && cost > 0 ? `$${cost}` : null],
      [
        "Latency",
        Number.isFinite(latency) && latency > 0 ? `${latency}s` : null,
      ],
      ["Models", models.length ? models.join(", ") : null],
      ["Errors", errors > 0 ? count(errors, "error") : null],
    ]),
  };
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
  return {
    ...preview,
    facts,
    sections: [
      ...(preview.sections ?? []),
      ...detailSection("Results", [
        ["Responses", Number.isFinite(sent) ? count(sent, "response") : null],
        [
          "Response rate",
          Number.isFinite(responseRate) && responseRate > 0
            ? `${Math.round(responseRate)}%`
            : null,
        ],
      ]),
    ],
  };
}

export function shapeErrorIssuePreview(
  issue: Schemas.ErrorTrackingIssueFull,
): EvidencePreview {
  const firstSeen = `First seen ${formatDay(issue.first_seen)}`;
  const assignee = issue.assignee
    ? `${issue.assignee.type} (${issue.assignee.id})`
    : null;
  return {
    title: issue.name || "Untitled issue",
    detail: issue.status
      ? `${humanizeStatus(issue.status)} · ${firstSeen}`
      : firstSeen,
    sections: detailSection("Issue", [
      ["Status", issue.status ? humanizeStatus(issue.status) : null],
      ["First seen", formatDay(issue.first_seen)],
      ["Assignee", assignee],
      [
        "Linked issues",
        issue.external_issues?.length
          ? count(issue.external_issues.length, "issue")
          : null,
      ],
      ["Affected cohort", issue.cohort?.name ?? null],
    ]),
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
    sections: detailSection("Session", [
      ["Duration", duration],
      [
        "Active time",
        typeof recording.active_seconds === "number"
          ? `${Math.round(recording.active_seconds)}s`
          : null,
      ],
      ["Start URL", recording.start_url],
      [
        "Clicks",
        recording.click_count ? count(recording.click_count, "click") : null,
      ],
      [
        "Console errors",
        recording.console_error_count
          ? count(recording.console_error_count, "console error")
          : null,
      ],
      [
        "Expires",
        recording.expiry_time ? formatDay(recording.expiry_time) : null,
      ],
    ]),
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
  const filters = isRecord(dashboard.filters) ? dashboard.filters : {};
  const variables = isRecord(dashboard.variables) ? dashboard.variables : {};
  return {
    title: dashboard.name || "Untitled dashboard",
    detail: dashboard.description || undefined,
    facts,
    sections: [
      ...detailSection("Dashboard", [
        ["Tiles", count(tiles.length, "tile")],
        ["Shared", dashboard.is_shared ? "Yes" : "No"],
        [
          "Filters",
          Object.keys(filters).length
            ? count(Object.keys(filters).length, "filter")
            : null,
        ],
        [
          "Variables",
          Object.keys(variables).length
            ? count(Object.keys(variables).length, "variable")
            : null,
        ],
        [
          "Last refreshed",
          dashboard.last_refresh ? formatDay(dashboard.last_refresh) : null,
        ],
      ]),
      ...detailSection(
        "Insights",
        names.slice(0, 6).map((name, index) => [`Tile ${index + 1}`, name]),
      ),
    ],
  };
}

export function shapeCohortPreview(cohort: Schemas.Cohort): EvidencePreview {
  const detail =
    typeof cohort.count === "number"
      ? count(cohort.count, "person", "people")
      : cohort.description || undefined;
  const type = cohort.is_static ? "Static" : "Dynamic";
  const experiments = cohort.experiment_set ?? [];
  return {
    title: cohort.name || "Untitled cohort",
    detail,
    facts: [type],
    sections: detailSection("Cohort", [
      ["Type", type],
      [
        "People",
        typeof cohort.count === "number"
          ? count(cohort.count, "person", "people")
          : null,
      ],
      [
        "Last calculated",
        cohort.last_calculation ? formatDay(cohort.last_calculation) : null,
      ],
      ["Calculation state", cohort.is_calculating ? "Calculating" : null],
      [
        "Calculation errors",
        cohort.errors_calculating ? String(cohort.errors_calculating) : null,
      ],
      [
        "Linked experiments",
        experiments.length ? count(experiments.length, "experiment") : null,
      ],
    ]),
  };
}

export function shapeActionPreview(action: Schemas.Action): EvidencePreview {
  const matchSteps = action.steps?.length ?? 0;
  return {
    title: action.name || "Untitled action",
    detail: action.description || undefined,
    facts: matchSteps ? [count(matchSteps, "match step")] : undefined,
    sections: [
      ...detailSection("Matching", [
        ["Match groups", matchSteps ? count(matchSteps, "group") : null],
        ["Calculation state", action.is_calculating ? "Calculating" : "Ready"],
        [
          "Last calculated",
          action.last_calculated_at
            ? formatDay(action.last_calculated_at)
            : null,
        ],
        [
          "Tags",
          action.tags?.length ? action.tags.map(String).join(", ") : null,
        ],
        ["Created", action.created_at ? formatDay(action.created_at) : null],
      ]),
      ...detailSection(
        "Match groups",
        (action.steps ?? []).map((step, index) => [
          `Group ${index + 1}`,
          actionStepSummary(step),
        ]),
      ),
    ],
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
    sections: detailSection("Ticket", [
      ["Status", status],
      ["Priority", priority],
      ["Channel", channel],
      [
        "Assignee",
        typeof assignedUser?.name === "string" ? assignedUser.name : null,
      ],
      [
        "Messages",
        typeof ticket.message_count === "number"
          ? count(ticket.message_count, "message")
          : null,
      ],
      ["Created", ticket.created_at ? formatDay(ticket.created_at) : null],
      ["Updated", ticket.updated_at ? formatDay(ticket.updated_at) : null],
      ["SLA due", ticket.sla_due_at ? formatDay(ticket.sla_due_at) : null],
    ]),
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
    sections: detailSection("Person", [
      [
        "Distinct IDs",
        person.distinct_ids.length
          ? person.distinct_ids.slice(0, 3).join(", ")
          : null,
      ],
      ["First seen", person.created_at ? formatDay(person.created_at) : null],
      [
        "Last seen",
        person.last_seen_at ? formatDay(person.last_seen_at) : null,
      ],
      ["Email", email],
      ["Country", stringValue(properties.$geoip_country_name)],
      ["Browser", stringValue(properties.$browser)],
    ]),
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
    sections: detailSection("Event", [
      [
        "First seen",
        definition.created_at ? formatDay(definition.created_at) : null,
      ],
      [
        "Last seen",
        definition.last_seen_at ? formatDay(definition.last_seen_at) : null,
      ],
      ["Action", definition.is_action ? "Yes" : "No"],
      [
        "Calculation state",
        definition.is_calculating ? "Calculating" : "Ready",
      ],
      [
        "Tags",
        definition.tags?.length ? definition.tags.map(String).join(", ") : null,
      ],
    ]),
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
  const questions = Array.isArray(survey.questions)
    ? survey.questions.length
    : 0;
  return {
    title: survey.name,
    detail,
    sections: [
      ...detailSection("Survey", [
        ["State", survey.archived ? "Archived" : detail],
        [
          "Type",
          typeof survey.type === "string" ? humanizeStatus(survey.type) : null,
        ],
        ["Questions", questions ? count(questions, "question") : null],
        [
          "Response limit",
          survey.responses_limit ? String(survey.responses_limit) : null,
        ],
        ["Starts", survey.start_date ? formatDay(survey.start_date) : null],
        ["Ends", survey.end_date ? formatDay(survey.end_date) : null],
      ]),
      ...detailSection(
        "Questions",
        (Array.isArray(survey.questions) ? survey.questions : [])
          .slice(0, 6)
          .map((question, index) => [
            `Question ${index + 1}`,
            surveyQuestionSummary(question),
          ]),
      ),
    ],
  };
}
