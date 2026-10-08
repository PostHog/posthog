import type { BlockPropsRecord } from "./blockDefinitions";

export const SQL_COLUMN_HINTS: Record<string, string> = {
  SqlTable: "Any columns. Each row of the result is a row of the table.",
  Metric:
    "Return one row. The first column is the value. An optional second column is the previous value, for the change badge.",
  Goal: "Return one row with the value in the first column.",
  Trend:
    "The first column is the x axis, a date or a label. Each other column is a series.",
  TopList: "Each row is a label, then a number.",
  Funnel: "Each row is a step, in order: the step name, then the count.",
  RecentEvents: "Each row is a time, the event, then a detail.",
};

export const SQL_BLOCK_TYPES = new Set(
  Object.keys(SQL_COLUMN_HINTS).filter((type) => type !== "SqlTable"),
);

const INTERVAL_FUNCTIONS: Record<string, string> = {
  hour: "toStartOfHour",
  day: "toStartOfDay",
  week: "toStartOfWeek",
  month: "toStartOfMonth",
};

const KNOWN_EVENTS: Record<string, string> = {
  $pageview: "Pageview",
  $autocapture: "Autocapture",
  $pageleave: "Pageleave",
};

function text(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

function texts(value: unknown, fallback: string[]): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
    ? value
    : fallback;
}

function literal(value: string): string {
  return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
}

function alias(value: string): string {
  return `\`${value.replace(/`/g, "")}\``;
}

function label(event: string): string {
  return KNOWN_EVENTS[event] ?? event;
}

function property(key: string): string {
  return /^[A-Za-z_$][\w$]*$/.test(key)
    ? `properties.${key}`
    : `properties.${alias(key)}`;
}

function unique(math: string): boolean {
  return math !== "total";
}

function aggregate(math: string): string {
  return unique(math) ? "count(DISTINCT person_id)" : "count()";
}

function aggregateFor(math: string, event: string): string {
  const condition = `event = ${literal(event)}`;
  return unique(math)
    ? `uniqIf(person_id, ${condition})`
    : `countIf(${condition})`;
}

function metricSql(props: BlockPropsRecord): string {
  const event = text(props.event, "$pageview");
  const math = text(props.math, "total");
  return `SELECT ${aggregate(math)} AS value\nFROM events\nWHERE event = ${literal(event)} AND {filters}`;
}

function trendSql(props: BlockPropsRecord, interval: string): string {
  const events = texts(props.events, ["$pageview"]);
  const math = text(props.math, "total");
  const bucket = INTERVAL_FUNCTIONS[interval] ?? INTERVAL_FUNCTIONS.day;
  const series = events
    .map((event) => `  ${aggregateFor(math, event)} AS ${alias(label(event))}`)
    .join(",\n");
  return `SELECT\n  ${bucket}(timestamp) AS period,\n${series}\nFROM events\nWHERE event IN (${events.map(literal).join(", ")}) AND {filters}\nGROUP BY period\nORDER BY period`;
}

function topListSql(props: BlockPropsRecord): string {
  const event = text(props.event, "$pageview");
  const math = text(props.math, "total");
  const breakdown = text(props.breakdown, "$pathname");
  const limit = typeof props.limit === "number" ? props.limit : 8;
  return `SELECT ${property(breakdown)} AS value, ${aggregate(math)} AS total\nFROM events\nWHERE event = ${literal(event)} AND {filters}\nGROUP BY value\nORDER BY total DESC\nLIMIT ${limit}`;
}

function funnelSql(props: BlockPropsRecord): string {
  const steps = texts(props.steps, ["$pageview", "$autocapture"]);
  const windowDays =
    typeof props.windowDays === "number" ? props.windowDays : 14;
  const conditions = steps.map((step) => `event = ${literal(step)}`).join(", ");
  const levels = `SELECT person_id, windowFunnel(${windowDays * 86400})(toDateTime(timestamp), ${conditions}) AS level\n  FROM events\n  WHERE event IN (${Array.from(new Set(steps)).map(literal).join(", ")}) AND {filters}\n  GROUP BY person_id`;
  const rows = steps
    .map(
      (step, index) =>
        `  SELECT ${literal(label(step))} AS step, countIf(level >= ${index + 1}) AS people, ${index + 1} AS position FROM levels`,
    )
    .join("\n  UNION ALL\n");
  return `WITH levels AS (\n  ${levels}\n)\nSELECT step, people FROM (\n${rows}\n)\nORDER BY position`;
}

function recentEventsSql(props: BlockPropsRecord): string {
  const limit = typeof props.limit === "number" ? props.limit : 12;
  return `SELECT timestamp, event, coalesce(toString(properties.$pathname), toString(properties.$current_url), '') AS place\nFROM events\nWHERE {filters}\nORDER BY timestamp DESC\nLIMIT ${limit}`;
}

export function builderSql(
  type: string,
  props: BlockPropsRecord,
  interval = "day",
): string {
  switch (type) {
    case "Metric":
    case "Goal":
      return metricSql(props);
    case "Trend":
      return trendSql(props, interval);
    case "TopList":
      return topListSql(props);
    case "Funnel":
      return funnelSql(props);
    case "RecentEvents":
      return recentEventsSql(props);
    default:
      return "SELECT event, count() AS total\nFROM events\nWHERE {filters}\nGROUP BY event\nORDER BY total DESC\nLIMIT 10";
  }
}
