import {
  escapeXmlAttr,
  type UploadableSkillSource,
  unescapeXmlAttr,
} from "@posthog/shared";
import { isUploadableSkillSource, parseXmlAttrs } from "./skillTags";

export const POSTHOG_OBJECT_KINDS = [
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
] as const;

export type PostHogObjectKind = (typeof POSTHOG_OBJECT_KINDS)[number];

const POSTHOG_OBJECT_KIND_SET: ReadonlySet<string> = new Set(
  POSTHOG_OBJECT_KINDS,
);

export function isPostHogObjectKind(value: string): value is PostHogObjectKind {
  return POSTHOG_OBJECT_KIND_SET.has(value);
}

export interface MentionChip {
  type:
    | "file"
    | "folder"
    | "command"
    | "error"
    | "experiment"
    | "insight"
    | "feature_flag"
    | "posthog_object"
    | "github_issue"
    | "github_pr";
  id: string;
  label: string;
  objectKind?: PostHogObjectKind;
  pastedText?: boolean;
  chipId?: string;
  skillPath?: string;
  skillSource?: UploadableSkillSource;
  skillName?: string;
}

export interface FileAttachment {
  id: string;
  label: string;
}

export interface EditorContent {
  segments: Array<
    { type: "text"; text: string } | { type: "chip"; chip: MentionChip }
  >;
  attachments?: FileAttachment[];
}

export function contentToPlainText(content: EditorContent): string {
  return content.segments
    .map((seg) => {
      if (seg.type === "text") return seg.text;
      const chip = seg.chip;
      if (chip.type === "file" || chip.type === "folder")
        return `@${chip.label}`;
      if (chip.type === "command") return `/${chip.label}`;
      if (chip.type === "posthog_object") return chip.label;
      return `@${chip.label}`;
    })
    .join("");
}

function isAbsolutePathLike(p: string): boolean {
  return p.startsWith("/") || p.startsWith("~") || /^[A-Za-z]:[\\/]/.test(p);
}

function escapeXmlText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function contentToXml(content: EditorContent): string {
  const inlineFilePaths = new Set<string>();
  const parts = content.segments.map((seg) => {
    if (seg.type === "text") return seg.text;
    const chip = seg.chip;
    const escapedId = escapeXmlAttr(chip.id);
    switch (chip.type) {
      case "file":
        inlineFilePaths.add(chip.id);
        return `<file path="${escapedId}" />`;
      case "folder":
        inlineFilePaths.add(chip.id);
        return `<folder path="${escapedId}" />`;
      case "command":
        if (chip.skillPath && chip.skillSource) {
          return `<skill name="${escapeXmlAttr(chip.skillName ?? chip.label)}" source="${escapeXmlAttr(chip.skillSource)}" path="${escapeXmlAttr(chip.skillPath)}" />`;
        }
        if (chip.id && chip.id !== chip.label && isAbsolutePathLike(chip.id)) {
          return `<folder path="${escapedId}" />`;
        }
        return `/${chip.label}`;
      case "error":
        return `<error id="${escapedId}" />`;
      case "experiment":
        return `<experiment id="${escapedId}" />`;
      case "insight":
        return `<insight id="${escapedId}" />`;
      case "feature_flag":
        return `<feature_flag id="${escapedId}" />`;
      case "posthog_object":
        if (!chip.objectKind) return chip.label;
        return chip.objectKind === "hogql"
          ? `<hogql>${escapeXmlText(chip.id)}</hogql>`
          : `<${chip.objectKind} id="${escapedId}" />`;
      case "github_issue":
      case "github_pr": {
        const labelMatch = chip.label.match(/^#(\d+)(?:\s*-\s*(.*))?$/);
        const number = labelMatch?.[1] ?? "";
        const title = labelMatch?.[2] ?? "";
        return `<${chip.type} number="${escapeXmlAttr(number)}" title="${escapeXmlAttr(title)}" url="${escapedId}" />`;
      }
      default:
        return `@${chip.label}`;
    }
  });

  // Append file tags for attachments not already referenced inline
  if (content.attachments) {
    for (const att of content.attachments) {
      if (!inlineFilePaths.has(att.id)) {
        parts.push(`<file path="${escapeXmlAttr(att.id)}" />`);
      }
    }
  }

  return parts.join("");
}

// Self-closing chip tags, plus the paired `<hogql>...</hogql>` form whose SQL
// rides in the tag body. contentToXml XML-escapes that body, so the body is
// captured here and decoded on the way into a chip.
const CHIP_TAG_REGEX =
  /<(file|folder|skill|error|experiment|insight|feature_flag|dashboard|replay|flag|survey|ticket|trace|eval|event|cohort|action|person|github_issue|github_pr)\b([^>]*?)\s*\/>|<hogql\b[^>]*>([\s\S]*?)<\/hogql>/g;

export function deriveFileLabel(filePath: string): string {
  const segments = filePath.split("/").filter(Boolean);
  const fileName = segments.pop() ?? filePath;
  const parentDir = segments.pop();
  return parentDir ? `${parentDir}/${fileName}` : fileName;
}

function chipFromTag(tag: string, rawAttrs: string): MentionChip | null {
  const attrs = parseXmlAttrs(rawAttrs);
  switch (tag) {
    case "file": {
      const path = attrs.path;
      if (!path) return null;
      return { type: "file", id: path, label: deriveFileLabel(path) };
    }
    case "folder": {
      const path = attrs.path;
      if (!path) return null;
      return { type: "folder", id: path, label: deriveFileLabel(path) };
    }
    case "skill": {
      const path = attrs.path;
      const name = attrs.name;
      const source = attrs.source;
      if (!path || !name || !isUploadableSkillSource(source)) {
        return null;
      }
      return {
        type: "command",
        id: path,
        label: name,
        skillPath: path,
        skillSource: source,
        skillName: name,
      };
    }
    case "error":
    case "experiment":
    case "insight":
    case "feature_flag": {
      const id = attrs.id;
      if (!id) return null;
      return { type: tag, id, label: id };
    }
    case "dashboard":
    case "replay":
    case "flag":
    case "survey":
    case "ticket":
    case "trace":
    case "eval":
    case "event":
    case "cohort":
    case "action":
    case "person": {
      const id = attrs.id;
      if (!id) return null;
      return {
        type: "posthog_object",
        objectKind: tag,
        id,
        label: id,
      };
    }
    case "github_issue":
    case "github_pr": {
      const number = attrs.number ?? "";
      const title = attrs.title ?? "";
      const url = attrs.url ?? "";
      if (!number && !url) return null;
      const label = title ? `#${number} - ${title}` : `#${number}`;
      return { type: tag, id: url, label };
    }
    default:
      return null;
  }
}

// A `<hogql>` reference carries the SQL as its tag body, XML-escaped by
// contentToXml. Decode it back to the raw query so editing a serialized message
// (e.g. a queued one) restores the chip instead of leaking `<hogql>...&lt;...`
// markup and a corrupted query.
function hogqlChipFromBody(body: string): MentionChip | null {
  const query = unescapeXmlAttr(body).trim();
  if (!query) return null;
  return {
    type: "posthog_object",
    objectKind: "hogql",
    id: query,
    label: query,
  };
}

export function xmlToContent(xml: string): EditorContent {
  const segments: EditorContent["segments"] = [];
  let lastIndex = 0;

  for (const match of xml.matchAll(CHIP_TAG_REGEX)) {
    const matchIndex = match.index ?? 0;
    const chip = match[1]
      ? chipFromTag(match[1], match[2] ?? "")
      : hogqlChipFromBody(match[3] ?? "");
    if (!chip) continue;

    if (matchIndex > lastIndex) {
      segments.push({ type: "text", text: xml.slice(lastIndex, matchIndex) });
    }
    segments.push({ type: "chip", chip });
    lastIndex = matchIndex + match[0].length;
  }

  if (lastIndex < xml.length) {
    segments.push({ type: "text", text: xml.slice(lastIndex) });
  }

  if (segments.length === 0) {
    segments.push({ type: "text", text: xml });
  }

  return { segments };
}

export function xmlToPlainText(xml: string): string {
  return contentToPlainText(xmlToContent(xml));
}

/** Wrap plain text in editor content as a single text segment, no chip parsing. */
export function textToContent(text: string): EditorContent {
  return { segments: [{ type: "text", text }] };
}

export function isContentEmpty(
  content: EditorContent | null | string,
): boolean {
  if (!content) return true;
  if (typeof content === "string") return !content.trim();
  if (content.attachments && content.attachments.length > 0) return false;
  if (!content.segments) return true;
  return content.segments.every(
    (seg) => seg.type === "text" && !seg.text.trim(),
  );
}

export function extractFilePaths(content: EditorContent): string[] {
  const filePaths: string[] = [];
  const seen = new Set<string>();

  for (const seg of content.segments) {
    if (
      seg.type === "chip" &&
      (seg.chip.type === "file" || seg.chip.type === "folder") &&
      !seen.has(seg.chip.id)
    ) {
      seen.add(seg.chip.id);
      filePaths.push(seg.chip.id);
    }
  }

  if (content.attachments) {
    for (const att of content.attachments) {
      if (!seen.has(att.id)) {
        seen.add(att.id);
        filePaths.push(att.id);
      }
    }
  }

  return filePaths;
}
