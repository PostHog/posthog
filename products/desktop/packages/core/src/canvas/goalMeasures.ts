import { firstNumericCell, numericCell } from "./contextDocument";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function insightCurrentValue(results: unknown): number | null {
  if (!Array.isArray(results) || results.length === 0) return null;

  if (Array.isArray(results[0])) {
    return firstNumericCell(results as unknown[][]);
  }

  const rows = results.filter(isRecord);
  if (rows.length === 0) return null;

  const isFunnel = rows.every((row) => "count" in row && "order" in row);
  if (isFunnel) {
    const first = numericCell(rows[0].count);
    const last = numericCell(rows[rows.length - 1].count);
    if (first === null || last === null || first === 0) return null;
    return Math.round((last / first) * 1000) / 10;
  }

  let total = 0;
  let found = false;
  for (const row of rows) {
    const aggregated = numericCell(row.aggregated_value);
    if (aggregated !== null) {
      total += aggregated;
      found = true;
      continue;
    }
    if (Array.isArray(row.data)) {
      for (const point of row.data) {
        const value = numericCell(point);
        if (value !== null) {
          total += value;
          found = true;
        }
      }
    }
  }
  return found ? total : null;
}
