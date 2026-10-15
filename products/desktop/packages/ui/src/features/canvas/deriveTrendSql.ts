import type { GoalPeriod } from "@posthog/core/canvas/contextDocument";
import {
  COMMA,
  maskLiterals,
  restoreLiterals,
  splitClauses,
  splitOn,
  wordPattern,
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
const AND = wordPattern("AND");
const OR = wordPattern("OR");

export interface DerivedTrend {
  sql: string;
  period: GoalPeriod;
}

const BUCKETS: Record<GoalPeriod, { truncate: string; window: string }> = {
  day: {
    truncate: "toStartOfDay",
    window: "timestamp >= now() - INTERVAL 30 DAY",
  },
  week: {
    truncate: "toStartOfWeek",
    window: "timestamp >= now() - INTERVAL 12 WEEK",
  },
  month: {
    truncate: "toStartOfMonth",
    window: "timestamp >= now() - INTERVAL 12 MONTH",
  },
};

export function deriveTrendSql(
  measureSql: string,
  period: GoalPeriod,
): DerivedTrend | null {
  const source = measureSql.trim().replace(/;\s*$/, "");
  if (!source) return null;
  const { masked, literals } = maskLiterals(source);
  const segments = splitClauses(masked.trim());
  if (segments[0]?.keyword !== "SELECT") return null;
  if (segments.some((segment) => BLOCKING.has(segment.keyword))) return null;
  const select = segments[0].body.trim();
  if (!select || splitOn(select, COMMA).length !== 1) return null;
  const from = segments
    .find((segment) => segment.keyword === "FROM")
    ?.body.trim();
  if (!from || !/^events\b/i.test(from)) return null;
  const where = segments
    .find((segment) => segment.keyword === "WHERE")
    ?.body.trim();
  const conditions = where ? withoutTimeFilters(where) : [];
  if (conditions === null) return null;
  const bucket = BUCKETS[period];
  const sql = [
    `SELECT ${bucket.truncate}(timestamp) AS period, ${select}`,
    `FROM ${from}`,
    `WHERE ${[...conditions, bucket.window].join(" AND ")}`,
    "GROUP BY period",
    "ORDER BY period ASC",
  ].join("\n");
  return { sql: restoreLiterals(sql, literals), period };
}

function withoutTimeFilters(where: string): string[] | null {
  if (/\bBETWEEN\b/i.test(where)) return null;
  if (splitOn(where, OR).length > 1) return null;
  return splitOn(where, AND)
    .filter((part) => !/\btimestamp\b/i.test(part))
    .map((part) => `(${part})`);
}
