import type { SourceFiles, SourceRange } from "./sourceEdits";

const MAX_TAG_LENGTH = 160;
const MAX_TEXT_LENGTH = 80;
const MAX_PROP_VALUE_LENGTH = 40;
const MAX_PROPS = 6;

export interface PageInstance {
  index: number;
  count: number;
}

export interface BlockReferenceInput {
  label: string;
  source: SourceRange | null;
  blockId: string | null;
  props: Record<string, unknown>;
  visibleText: string | null;
  instance: PageInstance | null;
}

function squash(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function openingTag(code: string): string {
  let depth = 0;
  let quote: string | null = null;
  for (let index = 0; index < code.length; index++) {
    const char = code[index];
    if (quote) {
      if (char === quote && code[index - 1] !== "\\") quote = null;
      continue;
    }
    if (char === '"' || char === "'" || char === "`") quote = char;
    else if (char === "{") depth++;
    else if (char === "}") depth--;
    else if (char === ">" && depth === 0) return code.slice(0, index + 1);
  }
  return code;
}

function occurrenceOf(
  text: string,
  needle: string,
  start: number,
): PageInstance | null {
  let count = 0;
  let index = 0;
  for (
    let at = text.indexOf(needle);
    at !== -1;
    at = text.indexOf(needle, at + 1)
  ) {
    count++;
    if (at <= start) index = count;
  }
  return count > 1 ? { index, count } : null;
}

function formatProps(props: Record<string, unknown>): string {
  return Object.entries(props)
    .filter(([key, value]) => key !== "blockId" && value !== undefined)
    .slice(0, MAX_PROPS)
    .map(([key, value]) =>
      typeof value === "string"
        ? `${key}="${clip(value, MAX_PROP_VALUE_LENGTH)}"`
        : `${key}={${clip(JSON.stringify(value), MAX_PROP_VALUE_LENGTH)}}`,
    )
    .join(" ");
}

export function blockReferencePrompt(
  input: BlockReferenceInput,
  files: SourceFiles,
): string {
  const { label, source, blockId, instance } = input;
  const where = source ? ` in ${source.file}` : "";
  if (blockId)
    return `Change only this ${label} with blockId ${blockId}${where}: `;

  const fileText = source ? files[source.file] : undefined;
  const tag =
    source && fileText !== undefined
      ? openingTag(fileText.slice(source.start, source.end))
      : null;
  const shownTag = tag ? clip(squash(tag), MAX_TAG_LENGTH) : null;
  const details: string[] = [];

  if (tag && source && fileText !== undefined) {
    const occurrence = occurrenceOf(fileText, tag, source.start);
    if (occurrence)
      details.push(
        `match ${occurrence.index} of ${occurrence.count} for this code in the file`,
      );
  }
  if (instance) {
    details.push(
      `number ${instance.index} of the ${instance.count} on the page that this code renders`,
    );
    const props = formatProps(input.props);
    if (props) details.push(`props ${props}`);
  }
  const bareTag = !shownTag || !shownTag.includes(" ");
  const text = input.visibleText ? squash(input.visibleText) : "";
  if (text && (instance || bareTag))
    details.push(`showing "${clip(text, MAX_TEXT_LENGTH)}"`);

  const code = shownTag ? ` \`${shownTag}\`` : "";
  const extra = details.length ? ` (${details.join(", ")})` : "";
  return `Change only this ${label}${code}${where}${extra}: `;
}
