function extractTextContent(item: unknown): string | null {
  if (!item || typeof item !== "object") return null;
  const record = item as Record<string, unknown>;
  if (typeof record.text === "string") return record.text;

  if (!record.content || typeof record.content !== "object") return null;
  const content = record.content as Record<string, unknown>;
  return typeof content.text === "string" ? content.text : null;
}

export function extractPlanText(toolCall: {
  rawInput?: { plan?: unknown } | null;
  content?: readonly unknown[] | null;
}): string | null {
  for (const item of toolCall.content ?? []) {
    const text = extractTextContent(item);
    if (text?.trim()) return text;
  }

  const rawPlan = toolCall.rawInput?.plan;
  if (typeof rawPlan === "string" && rawPlan.trim()) return rawPlan;
  return null;
}
