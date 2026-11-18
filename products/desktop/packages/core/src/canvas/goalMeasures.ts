import { firstNumericCell, numericCell } from "./contextDocument";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: number | null): value is number {
  return value !== null;
}

function seriesValues(row: Record<string, unknown>): number[] {
  const aggregated = numericCell(row.aggregated_value);
  if (aggregated !== null) return [aggregated];
  if (!Array.isArray(row.data)) return [];
  return row.data.map(numericCell).filter(isNumber);
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

  const values = rows.flatMap(seriesValues);
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0);
}
