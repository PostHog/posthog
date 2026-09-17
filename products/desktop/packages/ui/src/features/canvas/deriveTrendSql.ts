import {
  maskLiterals,
  restoreLiterals,
  splitClauses,
  splitTopLevel,
} from "./formatHogQL";

const BLOCKING = new Set([
  "GROUP BY",
  "HAVING",
  "UNION ALL",
  "WITH",
  "JOIN",
  "LEFT JOIN",
  "INNER JOIN",
  "CROSS JOIN",
]);
export type TrendPeriod = "day" | "week" | "month";

export interface DerivedTrend {
  sql: string;
  period: TrendPeriod;
}

const BUCKETS: Record<TrendPeriod, { fn: string; window: string }> = {
  day: { fn: "toStartOfDay", window: "timestamp >= now() - INTERVAL 30 DAY" },
  week: {
    fn: "toStartOfWeek",
    window: "timestamp >= now() - INTERVAL 12 WEEK",
  },
  month: {
    fn: "toStartOfMonth",
    window: "timestamp >= now() - INTERVAL 12 MONTH",
  },
};

export function trendPeriodFor(
  goalName: string,
  measureSql: string,
): TrendPeriod {
  const name = goalName.toLowerCase();
  if (/\bmonth/.test(name)) return "month";
  if (/\bweek/.test(name)) return "week";
  if (/\bdaily\b|\bday\b/.test(name)) return "day";
  const sql = measureSql.toLowerCase();
  if (/tostartofmonth|interval\s+\d+\s+month/.test(sql)) return "month";
  if (/tostartofweek|interval\s+\d+\s+week/.test(sql)) return "week";
  return "day";
}

/**
 * A goal's measure is one aggregate over events. The same aggregate grouped
 * by period gives its trend, so every goal draws a chart from the query a
 * person wrote. Returns null when the query is not that simple shape.
 */
export function deriveTrendSql(
  measureSql: string,
  period: TrendPeriod = "day",
): DerivedTrend | null {
  const source = measureSql.trim().replace(/;\s*$/, "");
  if (!source) return null;
  const { masked, literals } = maskLiterals(source);
  const segments = splitClauses(masked.trim());
  if (segments[0]?.keyword !== "SELECT") return null;
  if (segments.some((segment) => BLOCKING.has(segment.keyword))) return null;
  const select = segments[0].body.trim();
  if (!select || splitTopLevel(select, ",").length !== 1) return null;
  const from = segments.find((s) => s.keyword === "FROM")?.body.trim();
  if (!from || !/^events\b/i.test(from)) return null;
  const where = segments.find((s) => s.keyword === "WHERE")?.body.trim();
  const conditions = where ? withoutTimeFilters(where) : [];
  if (conditions === null) return null;
  const bucket = BUCKETS[period];
  const sql = [
    `SELECT ${bucket.fn}(timestamp) AS period, ${select}`,
    `FROM ${from}`,
    `WHERE ${[...conditions, bucket.window].join(" AND ")}`,
    "GROUP BY period",
    "ORDER BY period ASC",
  ].join("\n");
  return { sql: restoreLiterals(sql, literals), period };
}

function withoutTimeFilters(where: string): string[] | null {
  if (hasTopLevel(where, /\bOR\b/i)) return null;
  const parts = splitTopLevelWord(where, "AND");
  return parts
    .map((part) => part.trim())
    .filter((part) => part.length > 0 && !/\btimestamp\b/i.test(part))
    .map((part) => `(${part})`);
}

function hasTopLevel(text: string, word: RegExp): boolean {
  return splitTopLevelWord(text, "OR").length > 1 && word.test(text);
}

function splitTopLevelWord(text: string, word: string): string[] {
  const pattern = new RegExp(`^${word}\\b`, "i");
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    if (char === "(") depth += 1;
    if (char === ")") depth = Math.max(0, depth - 1);
    const atWordStart = index > 0 && text[index - 1] === " ";
    if (depth === 0 && atWordStart && pattern.test(text.slice(index))) {
      parts.push(text.slice(start, index));
      index += word.length;
      start = index;
      continue;
    }
    index += 1;
  }
  parts.push(text.slice(start));
  return parts;
}
