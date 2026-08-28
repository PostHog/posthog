import { unescapeXmlAttr } from "@posthog/shared";

// Object tags are the message-side counterpart of the `<file path="..."/>`
// attachment convention: agents embed references to PostHog objects in their
// replies, and hosts render them as live chips instead of raw text.
//
//   <insight id="9pQx3">checkout funnel</insight>
//   <flag id="42"/>
//   <hogql label="errors today">SELECT count() FROM events ...</hogql>
//
// This module is host-agnostic: it owns the kind registry (minus icons, which
// are a host concern) and the parser that turns free text into an ordered run
// of text and tag segments. Rendering lives in each host.

export interface ObjectKindMeta {
  /** Human name of the kind, e.g. "Insight". */
  kindLabel: string;
  /** Product the object comes from, e.g. "Product analytics". */
  source: string;
  /**
   * Project-relative PostHog web path. Returns null when this id has no direct
   * page; omitted when the kind has no canonical page at all.
   */
  webPath?: (encodedId: string, rawId: string) => string | null;
}

export const OBJECT_KINDS: Record<string, ObjectKindMeta> = {
  insight: {
    kindLabel: "Insight",
    source: "Product analytics",
    webPath: (id) => `/insights/${id}`,
  },
  // For hogql the "id" is the SQL itself; the chip opens the SQL editor.
  hogql: {
    kindLabel: "SQL query",
    source: "SQL editor",
    webPath: (id) => `/sql?open_query=${id}`,
  },
  dashboard: {
    kindLabel: "Dashboard",
    source: "Product analytics",
    webPath: (id) => `/dashboard/${id}`,
  },
  error: {
    kindLabel: "Error issue",
    source: "Error tracking",
    webPath: (id) => `/error_tracking/${id}`,
  },
  replay: {
    kindLabel: "Session replay",
    source: "Session replay",
    webPath: (id) => `/replay/${id}`,
  },
  flag: {
    kindLabel: "Feature flag",
    source: "Feature flags",
    // Flag pages only resolve by numeric id, so a flag cited by key gets no
    // direct URL until its preview resolves the numeric id.
    webPath: (id, raw) => (/^\d+$/.test(raw) ? `/feature_flags/${id}` : null),
  },
  experiment: {
    kindLabel: "Experiment",
    source: "Experiments",
    webPath: (id) => `/experiments/${id}`,
  },
  survey: {
    kindLabel: "Survey",
    source: "Surveys",
    webPath: (id) => `/surveys/${id}`,
  },
  ticket: {
    kindLabel: "Support tickets",
    source: "Conversations",
    webPath: (id) => `/support/tickets/${id}`,
  },
  trace: {
    kindLabel: "LLM trace",
    source: "AI observability",
    webPath: (id) => `/ai-observability/traces/${id}`,
  },
  eval: {
    kindLabel: "Evaluation",
    source: "AI evals",
    webPath: (id) => `/ai-evals/evaluations/${id}`,
  },
  event: {
    kindLabel: "Events",
    source: "Product analytics",
    webPath: (id, raw) =>
      /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(raw)
        ? `/data-management/events/${id}`
        : null,
  },
  cohort: {
    kindLabel: "Cohort",
    source: "Product analytics",
    webPath: (id) => `/cohorts/${id}`,
  },
  action: {
    kindLabel: "Action",
    source: "Product analytics",
    webPath: (id) => `/data-management/actions/${id}`,
  },
  person: {
    kindLabel: "Person",
    source: "Product analytics",
    webPath: (id) => `/persons/${id}`,
  },
};

/** Alternate tag names agents plausibly write, mapped to registry kinds. */
const OBJECT_KIND_ALIASES: Record<string, string> = {
  "session-replay": "replay",
  recording: "replay",
  "feature-flag": "flag",
  feature_flag: "flag",
  sql: "hogql",
};

export const GENERIC_OBJECT_KIND: ObjectKindMeta = {
  kindLabel: "Evidence",
  source: "PostHog",
};

/** Registry kind for a tag name, or null when the tag isn't an object tag. */
export function resolveObjectKindName(tag: string): string | null {
  if (OBJECT_KINDS[tag]) return tag;
  const alias = OBJECT_KIND_ALIASES[tag];
  return alias && OBJECT_KINDS[alias] ? alias : null;
}

export function getObjectKind(kind: string): ObjectKindMeta {
  return OBJECT_KINDS[kind] ?? GENERIC_OBJECT_KIND;
}

/** Project-relative PostHog web path for a reference, or null when it has none. */
export function objectWebPath(kind: string, id: string): string | null {
  const build = getObjectKind(kind).webPath;
  return build ? build(encodeURIComponent(id), id) : null;
}

export interface ObjectTagRef {
  /** Resolved registry kind. */
  kind: string;
  /** Object id, or the SQL text for a hogql reference. */
  id: string;
  /** Display text for the chip. */
  label: string;
}

export type ObjectTagSegment =
  | { type: "text"; value: string }
  | { type: "tag"; ref: ObjectTagRef };

const COMPLETE_TAG_RE =
  /<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(?:\/>|>([\s\S]*?)<\/\1\s*>)/g;
const ATTR_RE = /([a-z][\w-]*)\s*=\s*"([^"]*)"/g;
const KNOWN_TAG_START_RE = /<([a-z][\w-]*)/g;

export function parseObjectTagAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const match of raw.matchAll(ATTR_RE)) {
    attrs[match[1]] = unescapeXmlAttr(match[2]);
  }
  return attrs;
}

export function buildObjectTagRef(
  kind: string,
  attrs: Record<string, string>,
  body: string | undefined,
): ObjectTagRef | null {
  if (kind === "hogql") {
    const query = (body ?? "").trim();
    if (!query) return null;
    const label = attrs.title?.trim() || attrs.label?.trim() || "SQL query";
    return { kind, id: query, label };
  }
  const id = attrs.id?.trim();
  if (!id) return null;
  const label = attrs.title?.trim() || body?.trim() || id;
  return { kind, id, label };
}

/**
 * Index where a known object tag begins streaming but hasn't been completed,
 * or null. Complete tags are consumed before this runs, so any remaining
 * `<knownkind` marks a half-streamed tag whose markup should stay hidden.
 */
function incompleteTagStart(text: string): number | null {
  KNOWN_TAG_START_RE.lastIndex = 0;
  let found: number | null = null;
  let match: RegExpExecArray | null;
  // biome-ignore lint/suspicious/noAssignInExpressions: regex exec loop
  while ((match = KNOWN_TAG_START_RE.exec(text)) !== null) {
    if (resolveObjectKindName(match[1])) found = match.index;
  }
  return found;
}

/**
 * Split text into an ordered run of literal text and object-tag references.
 * Unknown tag names stay literal, and a still-streaming tag renders nothing
 * until its closing markup arrives.
 */
export function parseObjectTags(text: string): ObjectTagSegment[] {
  const segments: ObjectTagSegment[] = [];
  let cursor = 0;
  COMPLETE_TAG_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  // biome-ignore lint/suspicious/noAssignInExpressions: regex exec loop
  while ((match = COMPLETE_TAG_RE.exec(text)) !== null) {
    const kind = resolveObjectKindName(match[1]);
    if (!kind) continue;
    const ref = buildObjectTagRef(
      kind,
      parseObjectTagAttrs(match[2]),
      match[3],
    );
    if (!ref) continue;
    if (match.index > cursor) {
      segments.push({ type: "text", value: text.slice(cursor, match.index) });
    }
    segments.push({ type: "tag", ref });
    cursor = match.index + match[0].length;
  }

  let tail = text.slice(cursor);
  const partial = incompleteTagStart(tail);
  if (partial !== null) tail = tail.slice(0, partial);
  if (tail) segments.push({ type: "text", value: tail });
  return segments;
}
