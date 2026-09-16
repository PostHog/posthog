import { firstNumericCell } from "./contextDocument";

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The one number a saved insight stands for right now.
 *
 * A trends insight sums its series over the period (the total the insight
 * itself shows as a bold number). A funnel reads as the conversion from the
 * first step to the last, in percent. A HogQL insight reads its first cell.
 * Anything else returns null and the goal shows as unmeasured.
 */
export function insightCurrentValue(results: unknown): number | null {
  if (!Array.isArray(results) || results.length === 0) return null;

  if (Array.isArray(results[0])) {
    return firstNumericCell(results as unknown[][]);
  }

  const rows = results.filter(isRecord);
  if (rows.length === 0) return null;

  const isFunnel = rows.every((row) => "count" in row && "order" in row);
  if (isFunnel) {
    const first = asFiniteNumber(rows[0].count);
    const last = asFiniteNumber(rows[rows.length - 1].count);
    if (first === null || last === null || first === 0) return null;
    return Math.round((last / first) * 1000) / 10;
  }

  let total = 0;
  let found = false;
  for (const row of rows) {
    const aggregated = asFiniteNumber(row.aggregated_value);
    if (aggregated !== null) {
      total += aggregated;
      found = true;
      continue;
    }
    if (Array.isArray(row.data)) {
      for (const point of row.data) {
        const value = asFiniteNumber(point);
        if (value !== null) {
          total += value;
          found = true;
        }
      }
    }
  }
  return found ? total : null;
}
