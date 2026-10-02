import {
  buildObjectTagRef,
  parseObjectTagAttrs,
  resolveObjectKindName,
} from "@posthog/core/inbox/objectTags";
import {
  objectUrlLabel,
  type PostHogLinkContext,
  parsePostHogObjectUrl,
} from "@posthog/core/posthog-objects/objectUrls";

// Opening tags and closing tags are matched separately so an unmatched opener
// costs one regex step instead of a lazy scan to the end of the message; the
// closer for each opener comes from a precomputed per-tag position index.
const OPEN_TAG_PATTERN =
  /<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(\/>|>)/g;
const CLOSE_TAG_PATTERN = /<\/([a-z][\w-]*)\s*>/g;
const URL_PATTERN = /<(https?:\/\/[^>\n]+)>|https?:\/\/[^\s<>"'`[\]]+/g;
const LINK_LABEL_PATTERN = /(?<!!)\[([^[\]\n]*)\]\($/;
const MAX_REFERENCES = 50;
const MAX_OBJECT_ID_LENGTH = 16_384;
const MAX_LABEL_LENGTH = 255;

export interface PostHogObjectReference {
  kind: string;
  id: string;
  label: string;
}

// Remove inline code spans, matching CommonMark: an opening run of N backticks
// closes on the next run of exactly N, so a tag inside `code` or ``co`de`` stays
// literal. Runs are collected once and matched through per-length cursors, so a
// line full of unmatched runs costs one pass instead of a rescan per run.
function stripInlineCode(line: string): string {
  const runs: { start: number; end: number }[] = [];
  for (let i = 0; i < line.length; i++) {
    if (line[i] !== "`") continue;
    let j = i + 1;
    while (j < line.length && line[j] === "`") j++;
    runs.push({ start: i, end: j });
    i = j - 1;
  }
  if (runs.length < 2) return line;
  const runsByLength = new Map<number, number[]>();
  runs.forEach((run, index) => {
    const length = run.end - run.start;
    let list = runsByLength.get(length);
    if (!list) {
      list = [];
      runsByLength.set(length, list);
    }
    list.push(index);
  });
  const cursors = new Map<number, number>();
  let result = "";
  let copied = 0;
  let index = 0;
  while (index < runs.length) {
    const opener = runs[index];
    const length = opener.end - opener.start;
    const list = runsByLength.get(length) ?? [];
    let cursor = cursors.get(length) ?? 0;
    while (cursor < list.length && list[cursor] <= index) cursor++;
    cursors.set(length, cursor);
    if (cursor >= list.length) {
      index++;
      continue;
    }
    const closerIndex = list[cursor];
    result += line.slice(copied, opener.start);
    copied = runs[closerIndex].end;
    cursors.set(length, cursor + 1);
    index = closerIndex + 1;
  }
  return result + line.slice(copied);
}

// Blank out fenced code blocks so the tag parser never reads a citation the
// renderer shows as code. Mirrors the fence rules react-markdown applies:
// backtick or tilde fences of three or more, up to three leading spaces, closed
// only by a same-character run at least as long as the opener. Indented code
// blocks are left alone on purpose — a line-based strip would also drop real
// tags nested under list items; full parsing lives in the AST plugin instead.
function stripCode(markdown: string): string {
  let fence: { char: string; length: number } | null = null;
  return markdown
    .split("\n")
    .map((line) => {
      const fenceMatch = /^ {0,3}(`{3,}|~{3,})/.exec(line);
      if (fence) {
        const closes =
          fenceMatch !== null &&
          fenceMatch[1][0] === fence.char &&
          fenceMatch[1].length >= fence.length &&
          line.slice(fenceMatch[0].length).trim() === "";
        if (closes) fence = null;
        return "";
      }
      if (fenceMatch) {
        fence = { char: fenceMatch[1][0], length: fenceMatch[1].length };
        return "";
      }
      return stripInlineCode(line);
    })
    .join("\n");
}

interface TagMatch {
  name: string;
  rawAttributes: string;
  body: string;
  end: number;
}

// One pass over openers plus one over closers keeps parsing linear in the
// input size, where a single backreferencing regex retried the closing-tag
// search from every unmatched opener (quadratic on crafted input).
function* scanTags(text: string): Generator<TagMatch> {
  const closersByName = new Map<string, number[][]>();
  for (const close of text.matchAll(CLOSE_TAG_PATTERN)) {
    let positions = closersByName.get(close[1]);
    if (!positions) {
      positions = [];
      closersByName.set(close[1], positions);
    }
    positions.push([close.index, close.index + close[0].length]);
  }
  const cursors = new Map<string, number>();
  let nextAllowed = 0;
  for (const open of text.matchAll(OPEN_TAG_PATTERN)) {
    if (open.index < nextAllowed) continue;
    const name = open[1];
    const openEnd = open.index + open[0].length;
    if (open[3] === "/>") {
      nextAllowed = openEnd;
      yield { name, rawAttributes: open[2], body: "", end: openEnd };
      continue;
    }
    const positions = closersByName.get(name);
    if (!positions) continue;
    let cursor = cursors.get(name) ?? 0;
    while (cursor < positions.length && positions[cursor][0] < openEnd) {
      cursor++;
    }
    cursors.set(name, cursor);
    if (cursor >= positions.length) continue;
    const [closeStart, closeEnd] = positions[cursor];
    nextAllowed = closeEnd;
    yield {
      name,
      rawAttributes: open[2],
      body: text.slice(openEnd, closeStart),
      end: closeEnd,
    };
  }
}

function trimBareUrl(candidate: string): string {
  let url = candidate.replace(/[.,;:!?*_~]+$/, "");
  while (url.endsWith(")") && url.split(")").length > url.split("(").length) {
    url = url.slice(0, -1).replace(/[.,;:!?*_~]+$/, "");
  }
  return url;
}

function linkCandidates(text: string): { label: string; url: string }[] {
  return Array.from(text.matchAll(URL_PATTERN), (match) => ({
    label:
      LINK_LABEL_PATTERN.exec(
        text.slice(Math.max(0, match.index - MAX_LABEL_LENGTH), match.index),
      )?.[1] ?? "",
    url: match[1] ?? trimBareUrl(match[0]),
  }));
}

export function extractPostHogObjectReferences(
  markdown: string,
  links: PostHogLinkContext | null = null,
): PostHogObjectReference[] {
  const references: PostHogObjectReference[] = [];
  const seen = new Set<string>();
  const add = (kind: string, id: string, label: string): boolean => {
    if (id.length > MAX_OBJECT_ID_LENGTH) return false;
    const key = `${kind}\0${id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    references.push({
      kind,
      id,
      label: label.replace(/\s+/g, " ").trim().slice(0, MAX_LABEL_LENGTH),
    });
    return references.length >= MAX_REFERENCES;
  };
  const text = stripCode(markdown);
  for (const match of scanTags(text)) {
    const kind = resolveObjectKindName(match.name);
    if (!kind) continue;
    const ref = buildObjectTagRef(
      kind,
      parseObjectTagAttrs(match.rawAttributes),
      match.body,
    );
    if (ref && add(ref.kind, ref.id, ref.label)) return references;
  }
  if (!links) return references;
  for (const candidate of linkCandidates(text)) {
    const ref = parsePostHogObjectUrl(candidate.url, links);
    if (!ref) continue;
    const label =
      candidate.label.trim() && candidate.label.trim() !== candidate.url.trim()
        ? candidate.label
        : objectUrlLabel(ref);
    if (add(ref.kind, ref.id, label)) return references;
  }
  return references;
}
