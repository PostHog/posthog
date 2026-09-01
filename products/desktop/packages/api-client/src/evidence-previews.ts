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

export type ExperimentResultState =
  | "ready"
  | "draft"
  | "error"
  | "insufficient_data";

export interface ExperimentVariantResultPresentation {
  key: string;
  isControl: boolean;
  outcome: string;
  sampleContext: string;
  uplift: string | null;
  upliftValue: number | null;
  intervalBounds: [number, number] | null;
  upliftDirection: "positive" | "negative" | null;
  isImprovement: boolean | null;
  interval: string | null;
  pValue: string | null;
  chanceToWin: string | null;
  significance: "significant" | "not_significant" | "insufficient_data" | null;
}

export interface ExperimentMetricResultPresentation {
  id: string;
  name: string;
  metricType: "primary" | "secondary";
  state: "ready" | "error" | "insufficient_data";
  error: string | null;
  outcomeLabel: string;
  axisRange: number | null;
  bestVariant: {
    key: string;
    uplift: string;
    significance: ExperimentVariantResultPresentation["significance"];
    isImprovement: boolean | null;
  } | null;
  variants: ExperimentVariantResultPresentation[];
}

export interface ExperimentResultsPresentation {
  state: ExperimentResultState;
  stale: boolean;
  lastRefresh: string | null;
  primaryMetrics: ExperimentMetricResultPresentation[];
  secondaryMetrics: ExperimentMetricResultPresentation[];
}

export interface ExperimentMetricQueryResult {
  response: Schemas.ExperimentQueryResponse | null;
}

export interface EvidencePreview {
  /** The object's name in PostHog. */
  title: string;
  /** One line of context, e.g. the object's description or timeline. */
  detail?: string;
  /**
   * The object's lifecycle state as a badge: label plus a tone the UI maps to
   * a color. Kept out of `detail` so surfaces can style it.
   */
  status?: {
    label: string;
    tone: "positive" | "neutral" | "caution" | "critical";
  };
  /** Short scannable attributes, e.g. "100% rollout" or "42 clicks". */
  facts?: string[];
  /**
   * Headline numbers as label/value pairs. Full pages draw these as a stat
   * strip and then skip the fact chips; hover chips keep using `facts`.
   */
  stats?: Array<{ label: string; value: string }>;
  /**
   * Mini chart of the object's recent activity, oldest point first. `labels`
   * carries the bucket dates so a full page can draw a real chart with hover
   * values; the hover chip's sparkline ignores them.
   */
  spark?: { points: number[]; labels?: string[]; render: "line" | "bar" };
  /**
   * A titled multi-series time chart (e.g. experiment exposures per variant),
   * drawn with hover values on full pages; hover chips ignore it.
   */
  chart?: {
    title: string;
    labels: string[];
    series: Array<{ label: string; data: number[] }>;
    render: "line" | "bar";
  };
  sections?: EvidenceDetailSection[];
  experimentResults?: ExperimentResultsPresentation;
  /**
   * A dashboard's tiles, each resolvable to a live insight chart, so a full
   * page can render the metrics themselves rather than describe them.
   */
  tiles?: Array<{ shortId: string; name: string | null }>;
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

/** (day, count) rows -> the points' bucket dates, oldest first. */
export function dailySparkLabels(rows: unknown[][]): string[] {
  return rows.map((row) => String(row[0]));
}

function count(n: number, noun: string, plural = `${noun}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? noun : plural}`;
}

type QueryRecord = Record<string, unknown>;

function isRecord(value: unknown): value is QueryRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** An "Activity" section from (label, value) pairs, dropping empty values. */
export function activitySection(
  fields: Array<[string, string | null | undefined]>,
): EvidenceDetailSection[] {
  return detailSection("Activity", fields);
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

export function formatDay(iso: string): string {
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
  const singleRollout =
    groups.length === 1 && isRecord(groups[0])
      ? groups[0].rollout_percentage
      : null;
  const stats: Array<{ label: string; value: string }> = [
    ...(typeof singleRollout === "number"
      ? [{ label: "Rollout", value: `${singleRollout}%` }]
      : groups.length > 1
        ? [{ label: "Release conditions", value: String(groups.length) }]
        : []),
    ...(variants > 0 ? [{ label: "Variants", value: String(variants) }] : []),
    { label: "Type", value: flagType },
  ];
  return {
    title: flag.key,
    detail: name || undefined,
    status: flag.active
      ? { label: "Enabled", tone: "positive" }
      : { label: "Disabled", tone: "neutral" },
    facts,
    stats,
    sections: [
      ...detailSection("Configuration", [
        ["Type", flagType],
        [
          "Release conditions",
          groups.length ? count(groups.length, "condition") : "All users",
        ],
        [
          "Evaluation runtime",
          flag.evaluation_runtime === "all"
            ? "All runtimes"
            : flag.evaluation_runtime
              ? humanizeStatus(String(flag.evaluation_runtime))
              : null,
        ],
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
  let detail: string | undefined;
  let status: EvidencePreview["status"];
  // The API's status distinguishes paused and exposure-frozen experiments,
  // which both still have a start date and no end date, so the date range alone
  // reads them as "Running". The generated enum is narrower than the backend's
  // real values, so read the status as a plain string; fall back to the dates
  // for responses without one.
  const apiStatus: string | null =
    typeof experiment.status === "string" ? experiment.status : null;
  if (apiStatus === "paused" || apiStatus === "exposure_frozen") {
    status =
      apiStatus === "paused"
        ? { label: "Paused", tone: "caution" }
        : { label: "Exposure frozen", tone: "neutral" };
    if (experiment.start_date) {
      detail = `Started ${formatDay(experiment.start_date)}`;
    }
  } else if (experiment.end_date) {
    status = { label: "Ended", tone: "neutral" };
    detail = experiment.start_date
      ? `${formatDay(experiment.start_date)} to ${formatDay(experiment.end_date)}`
      : `Ended ${formatDay(experiment.end_date)}`;
  } else if (experiment.start_date) {
    status = { label: "Running", tone: "positive" };
    const days = Math.max(
      1,
      Math.ceil(
        (Date.now() - new Date(experiment.start_date).getTime()) / 86_400_000,
      ),
    );
    detail = `Day ${days} · Started ${formatDay(experiment.start_date)}`;
  } else {
    status = { label: "Draft", tone: "neutral" };
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
  const metricNames = (metrics: unknown): Array<[string, string | null]> =>
    (Array.isArray(metrics) ? metrics.filter(isRecord) : []).flatMap(
      (metric, index) => {
        const name =
          conciseValue(metric.name) ??
          (isRecord(metric.source) ? conciseValue(metric.source.name) : null);
        return name ? [[`Metric ${index + 1}`, name]] : [];
      },
    );
  const savedMetricNames: Array<[string, string | null]> = (
    experiment.saved_metrics ?? []
  ).flatMap((metric, index) =>
    typeof metric.name === "string" && metric.name
      ? [[`Shared metric ${index + 1}`, metric.name]]
      : [],
  );
  const stats: Array<{ label: string; value: string }> = [];
  if (experiment.start_date && !experiment.end_date) {
    const days = Math.max(
      1,
      Math.ceil(
        (Date.now() - new Date(experiment.start_date).getTime()) / 86_400_000,
      ),
    );
    stats.push({ label: "Running for", value: count(days, "day") });
  } else if (experiment.end_date) {
    stats.push({ label: "Ended", value: formatDay(experiment.end_date) });
  }
  if (variants.length > 0) {
    stats.push({ label: "Variants", value: String(variants.length) });
  }
  return {
    title: experiment.name,
    detail,
    status,
    facts,
    stats,
    sections: [
      ...detailSection("Configuration", [
        ["Hypothesis", experiment.description || null],
        ["Feature flag", experiment.feature_flag_key],
        ["Variants", variantSplit],
        ["Primary metric", primaryMetric?.name ?? null],
        ["Conclusion", outcome],
        ["Conclusion notes", experiment.conclusion_comment || null],
        [
          "Created",
          experiment.created_at ? formatDay(experiment.created_at) : null,
        ],
      ]),
      ...detailSection("Metrics", [
        ...metricNames(experiment.metrics),
        ...savedMetricNames,
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

interface ExperimentMetricDefinition {
  query: unknown;
  id: string;
  name: string;
  metricType: "primary" | "secondary";
  valueType: string | null;
  goal: string | null;
}

function metricName(metric: QueryRecord, index: number): string {
  const directName = conciseValue(metric.name);
  if (directName) return directName;
  for (const field of [
    "source",
    "completion_event",
    "start_event",
    "numerator",
  ]) {
    const source = metric[field];
    if (isRecord(source)) {
      const eventName = conciseValue(source.event) ?? conciseValue(source.name);
      if (eventName) return eventName;
    }
  }
  return `Metric ${index + 1}`;
}

function metricUuid(metric: QueryRecord, fallback: string): string {
  return conciseValue(metric.uuid) ?? fallback;
}

function orderedMetricDefinitions(
  experiment: Schemas.Experiment,
  metricType: "primary" | "secondary",
): ExperimentMetricDefinition[] {
  const inlineMetrics = ((metricType === "primary"
    ? experiment.metrics
    : experiment.metrics_secondary) ?? []) as unknown[];
  const definitions: ExperimentMetricDefinition[] = inlineMetrics.flatMap(
    (metric, index) =>
      isRecord(metric)
        ? [
            {
              query: metric,
              id: metricUuid(metric, `${metricType}-${index}`),
              name: metricName(metric, index),
              metricType,
              valueType: conciseValue(metric.metric_type),
              goal: conciseValue(metric.goal),
            },
          ]
        : [],
  );

  for (const savedMetric of experiment.saved_metrics ?? []) {
    const metadata = isRecord(savedMetric.metadata) ? savedMetric.metadata : {};
    if (metadata.type !== metricType || !isRecord(savedMetric.query)) continue;
    definitions.push({
      query: savedMetric.query,
      id: metricUuid(
        savedMetric.query,
        `${metricType}-saved-${savedMetric.saved_metric}`,
      ),
      name:
        savedMetric.name || metricName(savedMetric.query, definitions.length),
      metricType,
      valueType: conciseValue(savedMetric.query.metric_type),
      goal: conciseValue(savedMetric.query.goal),
    });
  }

  const experimentRecord = experiment as unknown as QueryRecord;
  const orderKey =
    metricType === "primary"
      ? "primary_metrics_ordered_uuids"
      : "secondary_metrics_ordered_uuids";
  const orderedUuids = Array.isArray(experimentRecord[orderKey])
    ? (experimentRecord[orderKey] as unknown[]).filter(
        (uuid): uuid is string => typeof uuid === "string",
      )
    : [];
  if (orderedUuids.length === 0) return definitions;
  const position = new Map(orderedUuids.map((uuid, index) => [uuid, index]));
  return definitions
    .map((definition, index) => ({ definition, index }))
    .sort(
      (left, right) =>
        (position.get(left.definition.id) ?? orderedUuids.length + left.index) -
        (position.get(right.definition.id) ??
          orderedUuids.length + right.index),
    )
    .map(({ definition }) => definition);
}

export function experimentMetricQueries(
  experiment: Schemas.Experiment,
  metricType: "primary" | "secondary",
): unknown[] {
  return orderedMetricDefinitions(experiment, metricType).map(
    (definition) => definition.query,
  );
}

function formatPercent(value: number, includeSign = false): string {
  const percentage = value * 100;
  const sign = includeSign && percentage > 0 ? "+" : "";
  return `${sign}${Math.abs(percentage) >= 10 ? percentage.toFixed(1) : percentage.toFixed(2)}%`;
}

function formatPValue(value: number): string {
  return value < 0.001 ? "< 0.001" : value.toFixed(3);
}

function validInterval(value: unknown): [number, number] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const lower = cellNumber(value[0]);
  const upper = cellNumber(value[1]);
  return lower === null || upper === null ? null : [lower, upper];
}

function outcomeValue(
  stats: Schemas.ExperimentStatsBaseValidated,
  valueType: string | null,
): { label: string; comparable: number | null; display: string } {
  const samples = stats.number_of_samples;
  const mean = samples > 0 ? stats.sum / samples : null;
  if (valueType === "funnel" || valueType === "retention") {
    return {
      label: valueType === "retention" ? "Retained" : "Conversions",
      comparable: mean,
      display: `${compactCount(stats.sum)} · ${mean === null ? "No rate" : formatPercent(mean)}`,
    };
  }
  if (valueType === "ratio") {
    const denominator = cellNumber(stats.denominator_sum);
    const ratio =
      denominator && denominator !== 0 ? stats.sum / denominator : null;
    return {
      label: "Ratio",
      comparable: ratio,
      display: `${compactCount(stats.sum)} numerator · ${ratio === null ? "No ratio" : ratio.toFixed(2)}`,
    };
  }
  return {
    label: "Outcome",
    comparable: mean,
    display: `${compactCount(stats.sum)} total · ${mean === null ? "No mean" : `${compactCount(mean)} per sample`}`,
  };
}

function hasInsufficientData(
  response: Schemas.ExperimentQueryResponse,
  stats: Schemas.ExperimentStatsBaseValidated[],
): boolean {
  if (response.significance_code === "not_enough_exposure") return true;
  return stats.some((entry) =>
    (entry.validation_failures ?? []).some(
      (failure) =>
        failure === "not-enough-exposures" ||
        failure === "not-enough-metric-data",
    ),
  );
}

const MIN_AXIS_RANGE = 0.05;
const MAX_AXIS_RANGE = 1.5;

function deltaAxisRange(
  rows: ExperimentVariantResultPresentation[],
): number | null {
  const bounds = rows.flatMap((row) =>
    row.intervalBounds ? row.intervalBounds.map(Math.abs) : [],
  );
  if (bounds.length === 0) return null;
  return Math.min(MAX_AXIS_RANGE, Math.max(MIN_AXIS_RANGE, ...bounds));
}

function shapeMetricResult(
  definition: ExperimentMetricDefinition,
  queryResult: ExperimentMetricQueryResult | undefined,
  exposures: Record<string, number>,
  experimentStarted: boolean,
): ExperimentMetricResultPresentation {
  const response = queryResult?.response;
  if (!experimentStarted) {
    return {
      id: definition.id,
      name: definition.name,
      metricType: definition.metricType,
      state: "insufficient_data",
      error: null,
      outcomeLabel: "Outcome",
      axisRange: null,
      bestVariant: null,
      variants: [],
    };
  }
  if (!response) {
    return {
      id: definition.id,
      name: definition.name,
      metricType: definition.metricType,
      state: "error",
      error: "Couldn't calculate this metric.",
      outcomeLabel: "Outcome",
      axisRange: null,
      bestVariant: null,
      variants: [],
    };
  }

  const baseline = response.baseline;
  const variants = response.variant_results ?? [];
  if (!baseline || variants.length === 0) {
    return {
      id: definition.id,
      name: definition.name,
      metricType: definition.metricType,
      state: "insufficient_data",
      error: null,
      outcomeLabel: "Outcome",
      axisRange: null,
      bestVariant: null,
      variants: [],
    };
  }

  const baselineOutcome = outcomeValue(baseline, definition.valueType);
  const allStats = [baseline, ...variants];
  const insufficient = hasInsufficientData(response, allStats);
  const upliftedRows: Array<{
    row: ExperimentVariantResultPresentation;
    value: number;
  }> = [];
  const rows = allStats.map((stats, index) => {
    const outcome = outcomeValue(stats, definition.valueType);
    const isControl = index === 0;
    const statsRecord = stats as unknown as QueryRecord;
    const interval = validInterval(
      statsRecord.confidence_interval ??
        statsRecord.credible_interval ??
        response.credible_intervals?.[stats.key],
    );
    const pValue = cellNumber(
      statsRecord.p_value ?? (variants.length === 1 ? response.p_value : null),
    );
    const chanceToWin = cellNumber(
      statsRecord.chance_to_win ?? response.probability?.[stats.key],
    );
    const significantValue =
      typeof statsRecord.significant === "boolean"
        ? statsRecord.significant
        : variants.length === 1 && typeof response.significant === "boolean"
          ? response.significant
          : null;
    const uplift =
      !isControl &&
      outcome.comparable !== null &&
      baselineOutcome.comparable !== null &&
      baselineOutcome.comparable !== 0
        ? outcome.comparable / baselineOutcome.comparable - 1
        : null;
    const builtRow: ExperimentVariantResultPresentation = {
      key: stats.key,
      isControl,
      outcome: outcome.display,
      sampleContext: [
        `${compactCount(stats.number_of_samples)} samples`,
        typeof exposures[stats.key] === "number"
          ? `${compactCount(exposures[stats.key])} exposed`
          : null,
      ]
        .filter(Boolean)
        .join(" · "),
      uplift: isControl || uplift === null ? null : formatPercent(uplift, true),
      upliftValue: isControl ? null : uplift,
      intervalBounds:
        isControl || !interval ? null : [interval[0], interval[1]],
      upliftDirection:
        uplift === null || uplift === 0
          ? null
          : uplift > 0
            ? ("positive" as const)
            : ("negative" as const),
      isImprovement:
        uplift === null || uplift === 0
          ? null
          : definition.goal === "decrease"
            ? uplift < 0
            : uplift > 0,
      interval:
        isControl || !interval
          ? null
          : `${formatPercent(interval[0], true)} to ${formatPercent(interval[1], true)}`,
      pValue: isControl || pValue === null ? null : formatPValue(pValue),
      chanceToWin:
        isControl || chanceToWin === null ? null : formatPercent(chanceToWin),
      significance: isControl
        ? null
        : insufficient
          ? ("insufficient_data" as const)
          : significantValue === null
            ? null
            : significantValue
              ? ("significant" as const)
              : ("not_significant" as const),
    };
    if (uplift !== null) {
      upliftedRows.push({ row: builtRow, value: uplift });
    }
    return builtRow;
  });
  const best = upliftedRows.reduce<{
    row: ExperimentVariantResultPresentation;
    value: number;
  } | null>((leader, entry) => {
    if (!leader) return entry;
    const isBetter =
      definition.goal === "decrease"
        ? entry.value < leader.value
        : entry.value > leader.value;
    return isBetter ? entry : leader;
  }, null);

  return {
    id: definition.id,
    name: definition.name,
    metricType: definition.metricType,
    state: insufficient ? "insufficient_data" : "ready",
    error: null,
    outcomeLabel: baselineOutcome.label,
    axisRange: deltaAxisRange(rows),
    bestVariant: best
      ? {
          key: best.row.key,
          uplift: formatPercent(best.value, true),
          significance: best.row.significance,
          isImprovement: best.row.isImprovement,
        }
      : null,
    variants: rows,
  };
}

export function shapeExperimentExposureChart(
  response: Schemas.ExperimentExposureQueryResponse | null,
): EvidencePreview["chart"] {
  if (!response) return undefined;
  const rows = response.timeseries.flatMap((series) =>
    series.days.map((day, index) => [
      day,
      series.variant,
      series.exposure_counts[index] ?? 0,
    ]),
  );
  const pivot = pivotDailyGroups(rows);
  if (!pivot) return undefined;
  return {
    title:
      pivot.omittedGroups > 0
        ? `Daily exposures by variant (top ${pivot.series.length} of ${pivot.series.length + pivot.omittedGroups})`
        : "Daily exposures by variant",
    labels: pivot.labels,
    series: pivot.series,
    render: "bar",
  };
}

export function shapeExperimentResults(
  experiment: Schemas.Experiment,
  exposuresResponse: Schemas.ExperimentExposureQueryResponse | null,
  primaryResults: ExperimentMetricQueryResult[],
  secondaryResults: ExperimentMetricQueryResult[],
): ExperimentResultsPresentation {
  const primaryMetrics = orderedMetricDefinitions(experiment, "primary").map(
    (definition, index) =>
      shapeMetricResult(
        definition,
        primaryResults[index],
        exposuresResponse?.total_exposures ?? {},
        !!experiment.start_date,
      ),
  );
  const secondaryMetrics = orderedMetricDefinitions(
    experiment,
    "secondary",
  ).map((definition, index) =>
    shapeMetricResult(
      definition,
      secondaryResults[index],
      exposuresResponse?.total_exposures ?? {},
      !!experiment.start_date,
    ),
  );
  const metrics = [...primaryMetrics, ...secondaryMetrics];
  const responses = [...primaryResults, ...secondaryResults]
    .map((result) => result.response as unknown as QueryRecord | null)
    .filter((response): response is QueryRecord => response !== null);
  const refreshTimes = responses.flatMap((response) => {
    const lastRefresh = conciseValue(response.last_refresh);
    return lastRefresh ? [lastRefresh] : [];
  });
  const staleRefreshTimes = experiment.end_date
    ? []
    : responses.flatMap((response) => {
        const lastRefresh = conciseValue(response.last_refresh);
        if (response.is_cached !== true || !lastRefresh) return [];
        const refreshedAt = new Date(lastRefresh).getTime();
        return Number.isFinite(refreshedAt) &&
          Date.now() - refreshedAt > 24 * 60 * 60 * 1000
          ? [lastRefresh]
          : [];
      });
  const state: ExperimentResultState = !experiment.start_date
    ? "draft"
    : metrics.some((metric) => metric.state === "error")
      ? "error"
      : metrics.length === 0 ||
          metrics.every((metric) => metric.state === "insufficient_data")
        ? "insufficient_data"
        : "ready";

  return {
    state,
    stale: staleRefreshTimes.length > 0,
    lastRefresh:
      staleRefreshTimes.sort()[0] ?? refreshTimes.sort().at(-1) ?? null,
    primaryMetrics,
    secondaryMetrics,
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

const MAX_CHART_SERIES = 6;

/**
 * (day, group, count) rows -> one series per group, zero-filled across the
 * days that appear anywhere in the grid. Days are sorted ascending. Groups are
 * ranked by total count (descending, then by name) and capped at
 * MAX_CHART_SERIES, so the highest-volume groups survive and the cut is
 * deterministic rather than dependent on row order. `omittedGroups` reports how
 * many were dropped, so the caller can say a chart is partial instead of hiding
 * groups silently.
 */
export function pivotDailyGroups(rows: unknown[][]): {
  labels: string[];
  series: Array<{ label: string; data: number[] }>;
  omittedGroups: number;
} | null {
  const labels = [...new Set(rows.map((row) => String(row[0])))].sort();
  const groupTotals = new Map<string, number>();
  for (const row of rows) {
    const group = String(row[1]);
    groupTotals.set(
      group,
      (groupTotals.get(group) ?? 0) + (cellNumber(row[2]) ?? 0),
    );
  }
  if (labels.length < 2 || groupTotals.size === 0) return null;
  const rankedGroups = [...groupTotals.keys()].sort((a, b) => {
    const byTotal = (groupTotals.get(b) ?? 0) - (groupTotals.get(a) ?? 0);
    return byTotal !== 0 ? byTotal : a < b ? -1 : a > b ? 1 : 0;
  });
  const shownGroups = rankedGroups.slice(0, MAX_CHART_SERIES);
  const labelIndex = new Map(labels.map((label, i) => [label, i]));
  const series = shownGroups.map((label) => ({
    label,
    data: labels.map(() => 0),
  }));
  const seriesByGroup = new Map(series.map((entry) => [entry.label, entry]));
  for (const row of rows) {
    const target = seriesByGroup.get(String(row[1]));
    const position = labelIndex.get(String(row[0]));
    if (target && position !== undefined) {
      target.data[position] = cellNumber(row[2]) ?? 0;
    }
  }
  return {
    labels,
    series,
    omittedGroups: rankedGroups.length - shownGroups.length,
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
  let state = preview.status;
  if (status?.status?.toLowerCase() === "stale") {
    facts.unshift("Stale");
    state = { label: "Stale", tone: "caution" };
    if (status.reason) detail = status.reason;
  }
  const points = dailySparkPoints(volumeRows);
  const total = points.reduce((sum, value) => sum + value, 0);
  if (total > 0) facts.push(`${compactCount(total)} calls (7d)`);
  const stats = [
    ...(preview.stats ?? []),
    ...(total > 0
      ? [{ label: "Calls in 7 days", value: compactCount(total) }]
      : []),
  ];
  return {
    ...preview,
    detail,
    status: state,
    facts,
    stats,
    spark:
      points.length > 1
        ? { points, labels: dailySparkLabels(volumeRows), render: "line" }
        : undefined,
    sections: [
      ...(preview.sections ?? []),
      ...detailSection("Activity", [
        ["Calls in 7 days", total > 0 ? compactCount(total) : null],
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
    detail: firstSeen,
    status: issue.status
      ? {
          label: humanizeStatus(issue.status),
          tone: issue.status === "active" ? "caution" : "neutral",
        }
      : undefined,
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

// Each rendered tile mounts a card that fires its own blocking insight
// refresh, and those queries share no concurrency limit, so an uncapped list
// opens one long-running request per tile at once when the page mounts. Bound
// the preview to a handful of tiles, matching the Insights section; the whole
// dashboard stays one "Open in PostHog" click away.
const MAX_DASHBOARD_CHART_TILES = 6;

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
  const chartTiles = tiles
    .flatMap((tile) => {
      if (!isRecord(tile) || !isRecord(tile.insight)) return [];
      const shortId = tile.insight.short_id;
      if (typeof shortId !== "string" || !shortId) return [];
      return [
        {
          shortId,
          name:
            typeof tile.insight.name === "string" ? tile.insight.name : null,
        },
      ];
    })
    .slice(0, MAX_DASHBOARD_CHART_TILES);
  return {
    title: dashboard.name || "Untitled dashboard",
    detail: dashboard.description || undefined,
    facts,
    tiles: chartTiles,
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

const PROPERTY_OPERATOR_LABELS: Record<string, string> = {
  exact: "is",
  is_not: "is not",
  icontains: "contains",
  not_icontains: "does not contain",
  regex: "matches",
  not_regex: "does not match",
  gt: "is greater than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  is_set: "is set",
  is_not_set: "is not set",
};

const NEGATED_PROPERTY_OPERATOR_LABELS: Record<string, string> = {
  exact: "is not",
  is_not: "is",
  icontains: "does not contain",
  not_icontains: "contains",
  regex: "does not match",
  not_regex: "matches",
  gt: "is at most",
  gte: "is less than",
  lt: "is at least",
  lte: "is greater than",
  is_set: "is not set",
  is_not_set: "is set",
};

const COUNT_OPERATOR_LABELS: Record<string, string> = {
  gte: "at least",
  lte: "at most",
  gt: "more than",
  lt: "fewer than",
  eq: "exactly",
  exact: "exactly",
};

// Older cohort builders store aliases the backend resolves to a canonical value.
// Desktop reads the raw filters blob, so it normalizes them itself. Mirror of
// BEHAVIORAL_VALUE_ALIASES in posthog/models/property/property.py.
const BEHAVIORAL_VALUE_ALIASES = new Map<string, string>([
  ["performed_event_multiple_times", "performed_event_multiple"],
]);

function describeBehavioralCriterion(criterion: QueryRecord): string | null {
  const event = conciseValue(criterion.key) ?? "an event";
  const window =
    typeof criterion.time_value === "number" && criterion.time_interval
      ? ` in the last ${criterion.time_value} ${String(criterion.time_interval)}${criterion.time_value === 1 ? "" : "s"}`
      : "";
  const negated = criterion.negation === true;
  const rawKind = String(criterion.value ?? "");
  const kind = BEHAVIORAL_VALUE_ALIASES.get(rawKind) ?? rawKind;
  if (kind === "performed_event")
    return `${negated ? "Did not complete" : "Completed"} ${event}${window}`;
  if (kind === "performed_event_multiple") {
    const times = asCount(criterion.operator_value);
    const operator = COUNT_OPERATOR_LABELS[String(criterion.operator)] ?? "";
    const bound =
      times !== null
        ? ` ${operator ? `${operator} ` : ""}${count(times, "time")}`
        : " multiple times";
    return `Completed ${event}${bound}${window}`;
  }
  if (kind === "performed_event_first_time")
    return `Completed ${event} for the first time${window}`;
  if (kind === "performed_event_regularly")
    return `Completed ${event} regularly${window}`;
  if (kind === "performed_event_sequence") {
    const then = conciseValue(criterion.seq_event);
    const verb = negated ? "Did not complete" : "Completed";
    return `${verb} ${event}${then ? ` then ${then}` : " in a sequence"}${window}`;
  }
  if (kind === "stopped_performing_event") return `Stopped doing ${event}`;
  if (kind === "restarted_performing_event")
    return `Returned to doing ${event}`;
  if (!kind) return null;
  return `${humanizeStatus(kind)}: ${event}${window}`;
}

function asCount(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function describeCohortCriterion(criterion: QueryRecord): string | null {
  const type = String(criterion.type ?? "");
  if (type === "behavioral") return describeBehavioralCriterion(criterion);
  const negated = criterion.negation === true;
  if (type === "cohort")
    return `Is ${negated ? "not " : ""}in cohort ${conciseValue(criterion.value) ?? "?"}`;
  if (type === "static-cohort")
    return `Is ${negated ? "not " : ""}in a static cohort`;
  if (type === "person" || type === "event" || type === "group") {
    const key = conciseValue(criterion.key);
    if (!key) return null;
    const rawOperator = String(criterion.operator ?? "");
    const labels = negated
      ? NEGATED_PROPERTY_OPERATOR_LABELS
      : PROPERTY_OPERATOR_LABELS;
    const operator =
      labels[rawOperator] ??
      (criterion.operator
        ? `${negated ? "not " : ""}${humanizeStatus(rawOperator).toLowerCase()}`
        : negated
          ? "is not"
          : "is");
    const value = conciseValue(criterion.value);
    const needsValue = !rawOperator.includes("is_set");
    return `${key} ${operator}${needsValue && value ? ` ${value}` : ""}`;
  }
  return null;
}

/**
 * A dynamic cohort's membership rules as prose, one field per match group.
 * The filter tree is untrusted JSON, so anything unrecognized is skipped
 * rather than rendered raw.
 */
export function cohortCriteriaSection(
  filters: unknown,
): EvidenceDetailSection[] {
  const properties =
    isRecord(filters) && isRecord(filters.properties)
      ? filters.properties
      : null;
  const groups = (
    Array.isArray(properties?.values) ? properties.values : []
  ).filter(isRecord);
  const outerAny = properties?.type === "OR";
  const fields = groups.flatMap((group, index) => {
    const criteria = (Array.isArray(group.values) ? group.values : [])
      .filter(isRecord)
      .map(describeCohortCriterion)
      .filter((line): line is string => line !== null);
    if (criteria.length === 0) return [];
    const joiner = group.type === "OR" ? " or " : " and ";
    const label =
      groups.length > 1
        ? `Group ${index + 1}${outerAny && index > 0 ? " (or)" : ""}`
        : "Criteria";
    return [[label, criteria.join(joiner)] as [string, string]];
  });
  return detailSection("Membership criteria", fields);
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
    stats: [
      ...(typeof cohort.count === "number"
        ? [{ label: "People", value: compactCount(cohort.count) }]
        : []),
      { label: "Type", value: type },
      ...(cohort.last_calculation
        ? [
            {
              label: "Last calculated",
              value: formatDay(cohort.last_calculation),
            },
          ]
        : []),
    ],
    sections: [
      ...detailSection("Cohort", [
        ["Description", cohort.description || null],
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
        ["Created", cohort.created_at ? formatDay(cohort.created_at) : null],
      ]),
      ...cohortCriteriaSection(cohort.filters),
    ],
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
    stats: [
      ...(definition.created_at
        ? [{ label: "First seen", value: formatDay(definition.created_at) }]
        : []),
      ...(definition.last_seen_at
        ? [{ label: "Last seen", value: formatDay(definition.last_seen_at) }]
        : []),
    ],
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
  let detail: string | undefined;
  let status: EvidencePreview["status"];
  if (survey.end_date) {
    status = { label: "Ended", tone: "neutral" };
    detail = `Ended ${formatDay(survey.end_date)}`;
  } else if (survey.start_date) {
    status = { label: "Running", tone: "positive" };
    detail = `Since ${formatDay(survey.start_date)}`;
  } else {
    status = { label: "Draft", tone: "neutral" };
  }
  const questions = Array.isArray(survey.questions)
    ? survey.questions.length
    : 0;
  return {
    title: survey.name,
    detail,
    status,
    sections: [
      ...detailSection("Survey", [
        ["State", survey.archived ? "Archived" : null],
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
