import { unescapeXmlAttr } from "@posthog/shared";

const OBJECT_KINDS = new Set([
  "insight",
  "hogql",
  "dashboard",
  "error",
  "replay",
  "flag",
  "experiment",
  "survey",
  "ticket",
  "trace",
  "eval",
  "event",
  "cohort",
  "action",
  "person",
]);

const OBJECT_ALIASES: Record<string, string> = {
  "session-replay": "replay",
  recording: "replay",
  "feature-flag": "flag",
  feature_flag: "flag",
  sql: "hogql",
};

const TAG_PATTERN =
  /<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(?:\/>|>([\s\S]*?)<\/\1\s*>)/g;
const ATTR_PATTERN = /([a-z][\w-]*)\s*=\s*"([^"]*)"/g;
const MAX_REFERENCES = 50;
const MAX_OBJECT_ID_LENGTH = 16_384;
const MAX_LABEL_LENGTH = 255;

export interface PostHogObjectReference {
  kind: string;
  id: string;
  label: string;
}

function stripCode(markdown: string): string {
  let inFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (/^\s*```/.test(line)) {
        inFence = !inFence;
        return "";
      }
      return inFence ? "" : line.replace(/`[^`\n]*`/g, "");
    })
    .join("\n");
}

function parseAttributes(raw: string): Record<string, string> {
  const attributes: Record<string, string> = {};
  for (const match of raw.matchAll(ATTR_PATTERN)) {
    attributes[match[1]] = unescapeXmlAttr(match[2]);
  }
  return attributes;
}

function normalizeKind(value: string): string | null {
  const kind = OBJECT_ALIASES[value] ?? value;
  return OBJECT_KINDS.has(kind) ? kind : null;
}

export function extractPostHogObjectReferences(
  markdown: string,
): PostHogObjectReference[] {
  const references: PostHogObjectReference[] = [];
  const seen = new Set<string>();
  for (const match of stripCode(markdown).matchAll(TAG_PATTERN)) {
    const kind = normalizeKind(match[1]);
    if (!kind) continue;
    const attributes = parseAttributes(match[2]);
    const body = (match[3] ?? "").trim();
    const id = (kind === "hogql" ? body : (attributes.id ?? "")).trim();
    if (!id || id.length > MAX_OBJECT_ID_LENGTH) continue;
    const key = `${kind}\0${id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const label = (
      attributes.label ??
      attributes.title ??
      body.replace(/\s+/g, " ") ??
      id
    ).trim();
    references.push({
      kind,
      id,
      label: (label || id).slice(0, MAX_LABEL_LENGTH),
    });
    if (references.length >= MAX_REFERENCES) break;
  }
  return references;
}
