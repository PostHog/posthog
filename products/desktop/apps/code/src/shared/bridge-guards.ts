export function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

export function boundedString(
  value: unknown,
  maxLength: number,
): value is string {
  return typeof value === "string" && value.length <= maxLength;
}

export function finiteRect(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) return null;
  const rect: Record<string, number> = {};
  for (const key of ["top", "left", "right", "bottom", "width", "height"]) {
    const field = value[key];
    if (typeof field !== "number" || !Number.isFinite(field)) return null;
    rect[key] = field;
  }
  return rect;
}
