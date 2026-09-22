import type {
  EditorContent,
  MentionChip,
} from "@posthog/core/message-editor/content";
import type { JSONContent } from "@tiptap/core";

type Segment = EditorContent["segments"][number];

const LIST_ITEM_PATTERN = /^(\s*)(?:([-*+])|(\d+)[.)])[ \t]+(.*)$/;
const FENCE_PATTERN = /^(\s*)```(\S*)\s*$/;

class SegmentBuilder {
  private readonly segments: Segment[] = [];

  text(text: string): void {
    if (!text) return;
    const last = this.segments[this.segments.length - 1];
    if (last?.type === "text") {
      last.text += text;
      return;
    }
    this.segments.push({ type: "text", text });
  }

  chip(chip: MentionChip): void {
    this.segments.push({ type: "chip", chip });
  }

  build(): Segment[] {
    return this.segments;
  }
}

function chipFromAttrs(attrs: Record<string, unknown>): MentionChip {
  return {
    type: attrs.type as MentionChip["type"],
    id: attrs.id as string,
    label: attrs.label as string,
    objectKind: attrs.objectKind as MentionChip["objectKind"],
    pastedText: attrs.pastedText as boolean | undefined,
    skillPath: attrs.skillPath as string | undefined,
    skillSource: attrs.skillSource as MentionChip["skillSource"],
    skillName: attrs.skillName as string | undefined,
  };
}

function chipToPlainText(chip: MentionChip): string {
  return chip.type === "command" ? `/${chip.label}` : `@${chip.label}`;
}

function hasCodeMark(node: JSONContent): boolean {
  return (node.marks ?? []).some((mark) => mark.type === "code");
}

function collectPlainText(node: JSONContent): string {
  if (node.type === "text") return node.text ?? "";
  if (node.type === "hardBreak") return "\n";
  if (node.type === "mentionChip" && node.attrs) {
    return chipToPlainText(chipFromAttrs(node.attrs));
  }
  return (node.content ?? []).map(collectPlainText).join("");
}

function emitInline(
  node: JSONContent,
  out: SegmentBuilder,
  indent: string,
): void {
  if (node.type === "text") {
    const text = node.text ?? "";
    out.text(hasCodeMark(node) ? `\`${text}\`` : text);
    return;
  }
  if (node.type === "hardBreak") {
    // Two trailing spaces make it a markdown line break rather than a soft wrap.
    out.text(`  \n${indent}`);
    return;
  }
  if (node.type === "mentionChip" && node.attrs) {
    out.chip(chipFromAttrs(node.attrs));
    return;
  }
  for (const child of node.content ?? []) {
    emitInline(child, out, indent);
  }
}

function emitCodeBlock(
  node: JSONContent,
  out: SegmentBuilder,
  indent: string,
): void {
  const language =
    typeof node.attrs?.language === "string" ? node.attrs.language : "";
  out.text(`\`\`\`${language}`);
  for (const line of collectPlainText(node).split("\n")) {
    out.text(`\n${indent}${line}`);
  }
  out.text(`\n${indent}\`\`\``);
}

function emitListItem(
  item: JSONContent,
  out: SegmentBuilder,
  contentIndent: string,
): void {
  const children = item.content ?? [];
  children.forEach((child, index) => {
    if (index > 0) {
      const tight = child.type === "bulletList" || child.type === "orderedList";
      out.text(`${tight ? "\n" : "\n\n"}${contentIndent}`);
    }
    emitBlock(child, out, contentIndent);
  });
}

function emitList(
  node: JSONContent,
  out: SegmentBuilder,
  indent: string,
): void {
  const ordered = node.type === "orderedList";
  const start = typeof node.attrs?.start === "number" ? node.attrs.start : 1;
  const items = node.content ?? [];
  items.forEach((item, index) => {
    if (index > 0) out.text(`\n${indent}`);
    const marker = ordered ? `${start + index}. ` : "- ";
    out.text(marker);
    emitListItem(item, out, indent + " ".repeat(marker.length));
  });
}

function emitBlock(
  node: JSONContent,
  out: SegmentBuilder,
  indent: string,
): void {
  if (node.type === "codeBlock") {
    emitCodeBlock(node, out, indent);
    return;
  }
  if (node.type === "bulletList" || node.type === "orderedList") {
    emitList(node, out, indent);
    return;
  }
  emitInline(node, out, indent);
}

function isEmptyParagraph(node: JSONContent): boolean {
  return node.type === "paragraph" && !collectPlainText(node).trim();
}

/** Serialize an editor document to markdown text segments plus mention chips. */
export function tiptapJsonToEditorContent(json: JSONContent): EditorContent {
  const out = new SegmentBuilder();
  const blocks = [...(json.type === "doc" ? (json.content ?? []) : [json])];
  // A doc ending in a list or code block gets a trailing paragraph so the caret
  // can escape the block; it is not part of the message.
  while (blocks.length > 1 && isEmptyParagraph(blocks[blocks.length - 1])) {
    blocks.pop();
  }
  blocks.forEach((block, index) => {
    // Blank line between blocks: a single newline would collapse to a space.
    if (index > 0) out.text("\n\n");
    emitBlock(block, out, "");
  });
  return { segments: out.build() };
}

interface Line {
  nodes: JSONContent[];
}

function segmentsToLines(segments: Segment[]): Line[] {
  const lines: Line[] = [{ nodes: [] }];

  const pushText = (text: string) => {
    if (!text) return;
    const line = lines[lines.length - 1];
    const last = line.nodes[line.nodes.length - 1];
    if (last?.type === "text") {
      last.text = (last.text ?? "") + text;
      return;
    }
    line.nodes.push({ type: "text", text });
  };

  for (const segment of segments) {
    if (segment.type === "chip") {
      lines[lines.length - 1].nodes.push({
        type: "mentionChip",
        attrs: {
          type: segment.chip.type,
          id: segment.chip.id,
          label: segment.chip.label,
          objectKind: segment.chip.objectKind,
          pastedText: segment.chip.pastedText ?? false,
          skillPath: segment.chip.skillPath,
          skillSource: segment.chip.skillSource,
          skillName: segment.chip.skillName,
        },
      });
      continue;
    }
    const parts = segment.text.split("\n");
    parts.forEach((part, index) => {
      if (index > 0) lines.push({ nodes: [] });
      pushText(part);
    });
  }

  return lines;
}

function leadingText(line: Line): string {
  const first = line.nodes[0];
  return first?.type === "text" ? (first.text ?? "") : "";
}

function lineText(line: Line): string {
  return line.nodes.map(collectPlainText).join("");
}

function isBlank(line: Line): boolean {
  return line.nodes.length === 0 || !lineText(line).trim();
}

interface ListItemMatch {
  indent: number;
  ordered: boolean;
  start: number;
  nodes: JSONContent[];
}

function matchListItem(line: Line): ListItemMatch | null {
  const match = LIST_ITEM_PATTERN.exec(leadingText(line));
  if (!match) return null;
  const [, indent, bullet, ordinal, rest] = match;
  const nodes: JSONContent[] = rest ? [{ type: "text", text: rest }] : [];
  nodes.push(...line.nodes.slice(1));
  return {
    indent: indent.length,
    ordered: !bullet,
    start: ordinal ? Number.parseInt(ordinal, 10) : 1,
    nodes,
  };
}

const INLINE_CODE_PATTERN = /`([^`\n]+)`/g;

function splitInlineCode(text: string): JSONContent[] {
  const nodes: JSONContent[] = [];
  let cursor = 0;
  for (const match of text.matchAll(INLINE_CODE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      nodes.push({ type: "text", text: text.slice(cursor, index) });
    }
    nodes.push({ type: "text", text: match[1], marks: [{ type: "code" }] });
    cursor = index + match[0].length;
  }
  if (cursor < text.length) {
    nodes.push({ type: "text", text: text.slice(cursor) });
  }
  return nodes;
}

function paragraphFrom(lines: Line[]): JSONContent {
  const content: JSONContent[] = [];
  lines.forEach((line, index) => {
    if (index > 0) content.push({ type: "hardBreak" });
    line.nodes.forEach((node, nodeIndex) => {
      const isLastText =
        node.type === "text" && nodeIndex === line.nodes.length - 1;
      // The trailing double space is the hard-break marker, not content.
      const text = isLastText
        ? (node.text ?? "").replace(/ {2}$/, "")
        : node.text;
      if (node.type === "text") {
        if (text) content.push(...splitInlineCode(text));
        return;
      }
      content.push(node);
    });
  });
  return { type: "paragraph", content };
}

function parseCodeBlock(
  lines: Line[],
  start: number,
): { node: JSONContent; next: number } {
  const match = FENCE_PATTERN.exec(leadingText(lines[start]));
  const indent = match?.[1] ?? "";
  const language = match?.[2] ?? "";
  const body: string[] = [];
  let index = start + 1;
  while (index < lines.length) {
    const text = lineText(lines[index]);
    if (text.trim() === "```") {
      index += 1;
      break;
    }
    body.push(text.startsWith(indent) ? text.slice(indent.length) : text);
    index += 1;
  }
  const code = body.join("\n");
  return {
    node: {
      type: "codeBlock",
      attrs: { language: language || null },
      content: code ? [{ type: "text", text: code }] : [],
    },
    next: index,
  };
}

function parseList(
  lines: Line[],
  start: number,
): { node: JSONContent; next: number } {
  const first = matchListItem(lines[start]) as ListItemMatch;
  const baseIndent = first.indent;
  const ordered = first.ordered;
  const items: JSONContent[] = [];
  let index = start;

  while (index < lines.length) {
    const match = matchListItem(lines[index]);
    if (!match || match.indent < baseIndent) break;

    if (match.indent > baseIndent) {
      const nested = parseList(lines, index);
      const lastItem = items[items.length - 1];
      if (lastItem) {
        lastItem.content = [...(lastItem.content ?? []), nested.node];
      } else {
        items.push({ type: "listItem", content: [nested.node] });
      }
      index = nested.next;
      continue;
    }

    if (match.ordered !== ordered) break;

    items.push({
      type: "listItem",
      content: [paragraphFrom([{ nodes: match.nodes }])],
    });
    index += 1;
  }

  return {
    node: ordered
      ? { type: "orderedList", attrs: { start: first.start }, content: items }
      : { type: "bulletList", content: items },
    next: index,
  };
}

/** Parse markdown text segments plus mention chips back into an editor document. */
export function editorContentToTiptapJson(content: EditorContent): JSONContent {
  const lines = segmentsToLines(content.segments);
  const blocks: JSONContent[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (isBlank(line)) {
      index += 1;
      continue;
    }

    if (FENCE_PATTERN.test(leadingText(line))) {
      const { node, next } = parseCodeBlock(lines, index);
      blocks.push(node);
      index = next;
      continue;
    }

    if (matchListItem(line)) {
      const { node, next } = parseList(lines, index);
      blocks.push(node);
      index = next;
      continue;
    }

    const paragraphLines: Line[] = [];
    while (index < lines.length) {
      const current = lines[index];
      if (
        isBlank(current) ||
        matchListItem(current) ||
        FENCE_PATTERN.test(leadingText(current))
      ) {
        break;
      }
      paragraphLines.push(current);
      index += 1;
    }
    blocks.push(paragraphFrom(paragraphLines));
  }

  if (blocks.length === 0) {
    blocks.push({ type: "paragraph", content: [] });
  }

  return { type: "doc", content: blocks };
}
