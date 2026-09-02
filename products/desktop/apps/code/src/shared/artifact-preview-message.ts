const ARTIFACT_BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";
const MAX_ITEMS = 500;
const MAX_ID_LENGTH = 128;
const MAX_CHANNEL_LENGTH = 256;
const MAX_QUOTE_LENGTH = 10_000;
const CONTEXT_LENGTH = 32;

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function boundedString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length <= maxLength;
}

function finiteRect(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) return null;
  const rect: Record<string, number> = {};
  for (const key of ["top", "left", "right", "bottom", "width", "height"]) {
    const field = value[key];
    if (typeof field !== "number" || !Number.isFinite(field)) return null;
    rect[key] = field;
  }
  return rect;
}

export function sanitizeArtifactBridgeMessage(
  value: unknown,
): Record<string, unknown> | null {
  if (
    !isRecord(value) ||
    value.marker !== ARTIFACT_BRIDGE_MARKER ||
    !boundedString(value.channel, MAX_CHANNEL_LENGTH)
  ) {
    return null;
  }
  const base = {
    marker: ARTIFACT_BRIDGE_MARKER,
    channel: value.channel,
  };
  if (value.type === "ready") return { ...base, type: "ready" };
  if (value.type === "selection-position") {
    const rect = finiteRect(value.rect);
    return rect ? { ...base, type: "selection-position", rect } : null;
  }
  if (
    value.type === "activate" &&
    boundedString(value.id, MAX_ID_LENGTH) &&
    value.id.length > 0
  ) {
    return { ...base, type: "activate", id: value.id };
  }
  if (value.type === "resolutions" && Array.isArray(value.items)) {
    if (value.items.length > MAX_ITEMS) return null;
    const items: { id: string; status: string }[] = [];
    for (const item of value.items) {
      if (
        !isRecord(item) ||
        !boundedString(item.id, MAX_ID_LENGTH) ||
        item.id.length === 0 ||
        !["exact", "reanchored", "orphaned"].includes(String(item.status))
      ) {
        return null;
      }
      items.push({ id: item.id, status: String(item.status) });
    }
    return { ...base, type: "resolutions", items };
  }
  if (value.type !== "selection" || !isRecord(value.anchor)) return null;
  const anchor = value.anchor;
  if (
    anchor.kind !== "text" ||
    !boundedString(anchor.quote, MAX_QUOTE_LENGTH) ||
    anchor.quote.length === 0 ||
    !boundedString(anchor.prefix, CONTEXT_LENGTH) ||
    !boundedString(anchor.suffix, CONTEXT_LENGTH) ||
    !Number.isInteger(anchor.start) ||
    !Number.isInteger(anchor.end) ||
    Number(anchor.start) < 0 ||
    Number(anchor.end) <= Number(anchor.start)
  ) {
    return null;
  }
  const rect = finiteRect(value.rect);
  const triggerRect = finiteRect(value.triggerRect);
  if (!rect || !triggerRect) return null;
  return {
    ...base,
    type: "selection",
    anchor: {
      kind: "text",
      quote: anchor.quote,
      prefix: anchor.prefix,
      suffix: anchor.suffix,
      start: anchor.start,
      end: anchor.end,
    },
    rect,
    triggerRect,
  };
}
