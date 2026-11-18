import {
  BLOCK_DEFINITIONS,
  BLOCK_ICONS_PATH,
  BLOCK_RUNTIME_PATH,
  type BlockDefinition,
  type BlockGroup,
  type BlockPropsRecord,
  type BlockPropValue,
  componentPath,
} from "./blockDefinitions";
import { withLibraryFile } from "./blockLibrarySync";
import { BLOCK_COMPONENT_SOURCES } from "./componentSources";

export type SourceFiles = Record<string, string>;

export interface SourceRange {
  file: string;
  start: number;
  end: number;
}

export type DropPlace = "before" | "after" | "left" | "right" | "inside";

export interface GridGrowth extends SourceRange {
  columns: number;
}

export interface SourceDropTarget extends SourceRange {
  place: DropPlace;
  grow?: GridGrowth;
}

const MAX_GRID_COLUMNS = 4;

const ROW_CLASS = "grid gap-4 sm:grid-cols-2";

export function newBlockId(): string {
  return `b-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

function jsxString(value: string): string {
  if (/["{}<>\n\\]/.test(value)) return `{${JSON.stringify(value)}}`;
  return `"${value}"`;
}

function jsxAttribute(name: string, value: BlockPropValue): string | null {
  if (value === undefined || value === "") return null;
  if (value === true) return name;
  if (typeof value === "string") return `${name}=${jsxString(value)}`;
  return `${name}={${JSON.stringify(value)}}`;
}

export function componentJsx(
  component: string,
  blockId: string,
  props: BlockPropsRecord,
): string {
  const attributes = [
    `blockId="${blockId}"`,
    ...Object.entries(props)
      .filter(([name]) => name !== "blockId")
      .map(([name, value]) => jsxAttribute(name, value)),
  ].filter((attribute): attribute is string => attribute !== null);
  return `<${component} ${attributes.join(" ")} />`;
}

export function blockJsx(
  definition: BlockDefinition,
  blockId: string,
  props: BlockPropsRecord,
): string {
  if (definition.component) {
    return componentJsx(definition.component, blockId, props);
  }
  return definition.element ?? "";
}

function lineStart(source: string, offset: number): number {
  return source.lastIndexOf("\n", offset - 1) + 1;
}

function indentAt(source: string, offset: number): string {
  const start = lineStart(source, offset);
  const match = /^[ \t]*/.exec(source.slice(start, offset));
  return match ? match[0] : "";
}

function relativeImport(fromFile: string, toFile: string): string {
  const from = fromFile.split("/").slice(0, -1);
  const to = toFile.replace(/\.(tsx|ts|jsx|js)$/, "").split("/");
  let shared = 0;
  while (shared < from.length && from[shared] === to[shared]) shared += 1;
  const up = from.length - shared;
  const rest = to.slice(shared).join("/");
  return up === 0 ? `./${rest}` : `${"../".repeat(up)}${rest}`;
}

function importEnd(source: string): number {
  const pattern =
    /^import[\s\S]*?from\s+["'][^"']+["'];?[^\n]*\n|^import\s+["'][^"']+["'];?[^\n]*\n/gm;
  let end = 0;
  for (const match of source.matchAll(pattern)) {
    const before = source.slice(0, match.index ?? 0);
    const onlyImports = before.replace(pattern, "").trim().length === 0;
    if (!onlyImports) break;
    end = (match.index ?? 0) + match[0].length;
  }
  return end;
}

export function withImport(
  source: string,
  name: string,
  specifier: string,
): string {
  const existing = new RegExp(
    `import\\s*\\{[^}]*\\b${name}\\b[^}]*\\}\\s*from\\s*["']${specifier.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["']`,
  );
  if (existing.test(source)) return source;
  const at = importEnd(source);
  const line = `import { ${name} } from "${specifier}";\n`;
  return source.slice(0, at) + line + source.slice(at);
}

function withBlockFiles(files: SourceFiles, component: string): SourceFiles {
  const shared = withLibraryFile(
    withLibraryFile(files, BLOCK_RUNTIME_PATH),
    BLOCK_ICONS_PATH,
  );
  return withLibraryFile(shared, componentPath(component));
}

function withComponentImport(
  files: SourceFiles,
  file: string,
  component: string,
): SourceFiles {
  const source = files[file];
  if (source === undefined) return files;
  const specifier = relativeImport(file, componentPath(component));
  return { ...files, [file]: withImport(source, component, specifier) };
}

function insertInside(
  source: string,
  target: SourceDropTarget,
  snippet: string,
): string {
  const element = source.slice(target.start, target.end);
  const close = element.lastIndexOf("</");
  if (close === -1)
    return insertText(source, { ...target, place: "after" }, snippet);
  const at = target.start + close;
  const outer = indentAt(source, target.start);
  const closeLine = lineStart(source, at);
  if (source.slice(closeLine, at).trim().length === 0) {
    return `${source.slice(0, closeLine)}${outer}  ${snippet}\n${source.slice(closeLine)}`;
  }
  return `${source.slice(0, at)}\n${outer}  ${snippet}\n${outer}${source.slice(at)}`;
}

function isExpressionRoot(source: string, start: number): boolean {
  const before = source.slice(Math.max(0, start - 200), start).trimEnd();
  return (
    /(?:\breturn|=>|\?|:|&&|\|\|)\s*\(?$/.test(before) &&
    !/[{,]\s*$/.test(before)
  );
}

function wrapPair(
  source: string,
  target: SourceDropTarget,
  snippet: string,
  open: string,
  close: string,
): string {
  const indent = indentAt(source, target.start);
  const inner = `${indent}  `;
  const existing = source
    .slice(target.start, target.end)
    .replace(/\n/g, "\n  ");
  const snippetFirst = target.place === "before" || target.place === "left";
  const children = snippetFirst
    ? `${inner}${snippet}\n${inner}${existing}`
    : `${inner}${existing}\n${inner}${snippet}`;
  return `${source.slice(0, target.start)}${open}\n${children}\n${indent}${close}${source.slice(target.end)}`;
}

function insertText(
  source: string,
  target: SourceDropTarget,
  snippet: string,
): string {
  if (target.place === "inside") return insertInside(source, target, snippet);
  const rootPosition =
    (target.place === "before" || target.place === "after") &&
    isExpressionRoot(source, target.start);
  if (rootPosition) return wrapPair(source, target, snippet, "<>", "</>");
  const indent = indentAt(source, target.start);
  if (target.place === "before") {
    const at = lineStart(source, target.start);
    const leading =
      source.slice(at, target.start).trim().length === 0 ? at : target.start;
    return `${source.slice(0, leading)}${indent}${snippet}\n${source.slice(leading)}`;
  }
  if (target.place === "after") {
    return `${source.slice(0, target.end)}\n${indent}${snippet}${source.slice(target.end)}`;
  }
  return wrapPair(
    source,
    target,
    snippet,
    `<div className="${ROW_CLASS}">`,
    "</div>",
  );
}

export function insertBlock(
  files: SourceFiles,
  target: SourceDropTarget,
  definition: BlockDefinition,
  props: BlockPropsRecord,
  blockId: string,
): SourceFiles {
  const source = files[target.file];
  if (source === undefined) return files;
  const snippet = blockJsx(definition, blockId, props);
  let next: SourceFiles = {
    ...files,
    [target.file]: insertText(source, target, snippet),
  };
  if (target.grow) next = growGrid(next, target.grow);
  if (definition.component) {
    next = withBlockFiles(next, definition.component);
    next = withComponentImport(next, target.file, definition.component);
  }
  return next;
}

function growGrid(files: SourceFiles, grid: GridGrowth): SourceFiles {
  const source = files[grid.file];
  if (source === undefined || grid.columns >= MAX_GRID_COLUMNS) return files;
  const tagEnd = source.indexOf(">", grid.start);
  if (tagEnd === -1 || tagEnd > grid.end) return files;
  const openingTag = source.slice(grid.start, tagEnd);
  const pattern = new RegExp(
    `((?:^|[\\s"'\`])(?:[a-z0-9@]+:)*grid-cols-)${grid.columns}(?![0-9])`,
    "g",
  );
  if (!pattern.test(openingTag)) return files;
  const grown = openingTag.replace(pattern, `$1${grid.columns + 1}`);
  return {
    ...files,
    [grid.file]: source.slice(0, grid.start) + grown + source.slice(tagEnd),
  };
}

function removeText(source: string, range: SourceRange): string {
  const start = lineStart(source, range.start);
  const ownLine = source.slice(start, range.start).trim().length === 0;
  const lineEnd = source.indexOf("\n", range.end);
  const restOfLine = source.slice(
    range.end,
    lineEnd === -1 ? source.length : lineEnd,
  );
  if (ownLine && restOfLine.trim().length === 0) {
    return (
      source.slice(0, start) +
      source.slice(lineEnd === -1 ? source.length : lineEnd + 1)
    );
  }
  return source.slice(0, range.start) + source.slice(range.end);
}

export function removeRange(
  files: SourceFiles,
  range: SourceRange,
): SourceFiles {
  const source = files[range.file];
  if (source === undefined) return files;
  return { ...files, [range.file]: removeText(source, range) };
}

export function rangeText(files: SourceFiles, range: SourceRange): string {
  return files[range.file]?.slice(range.start, range.end) ?? "";
}

export function replaceRange(
  files: SourceFiles,
  range: SourceRange,
  text: string,
): SourceFiles {
  const source = files[range.file];
  if (source === undefined) return files;
  return {
    ...files,
    [range.file]: source.slice(0, range.start) + text + source.slice(range.end),
  };
}

function shiftTarget(
  target: SourceDropTarget,
  removed: SourceRange,
  removedLength: number,
): SourceDropTarget {
  if (target.file !== removed.file) return target;
  if (target.start >= removed.end) {
    return {
      ...target,
      start: target.start - removedLength,
      end: target.end - removedLength,
    };
  }
  if (target.start <= removed.start && target.end >= removed.end) {
    return { ...target, end: target.end - removedLength };
  }
  return target;
}

export function moveRange(
  files: SourceFiles,
  range: SourceRange,
  target: SourceDropTarget,
): SourceFiles {
  const text = rangeText(files, range);
  const inside =
    target.file === range.file &&
    target.start >= range.start &&
    target.end <= range.end;
  if (!text || inside) return files;
  const before = files[range.file] ?? "";
  const afterRemoval = removeRange(files, range);
  const removedLength = before.length - (afterRemoval[range.file] ?? "").length;
  const shifted = shiftTarget(target, range, removedLength);
  const source = afterRemoval[shifted.file];
  if (source === undefined) return files;
  let next: SourceFiles = {
    ...afterRemoval,
    [shifted.file]: insertText(source, shifted, text.trim()),
  };
  const component = /^<([A-Z][A-Za-z0-9]*)/.exec(text.trim())?.[1];
  if (
    component &&
    shifted.file !== range.file &&
    BLOCK_COMPONENT_SOURCES[component]
  ) {
    next = withComponentImport(next, shifted.file, component);
  }
  return next;
}

export function duplicateRange(
  files: SourceFiles,
  range: SourceRange,
  blockId: string,
): SourceFiles {
  const text = rangeText(files, range).replace(
    /blockId="[^"]*"/,
    `blockId="${blockId}"`,
  );
  const source = files[range.file];
  if (!text || source === undefined) return files;
  return {
    ...files,
    [range.file]: insertText(source, { ...range, place: "after" }, text),
  };
}

interface JsxAttribute {
  name: string | null;
  start: number;
  end: number;
}

interface OpeningTag {
  attributes: JsxAttribute[];
  insertAt: number;
}

function skipQuoted(source: string, from: number, quote: string): number {
  let index = from + 1;
  while (index < source.length && source[index] !== quote) {
    if (source[index] === "\\") index += 1;
    index += 1;
  }
  return index + 1;
}

function skipBraces(source: string, from: number): number {
  let depth = 0;
  let index = from;
  while (index < source.length) {
    const char = source[index];
    if (char === '"' || char === "'" || char === "`") {
      index = skipQuoted(source, index, char);
      continue;
    }
    if (char === "{") depth += 1;
    if (char === "}") {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
    index += 1;
  }
  return index;
}

function scanOpeningTag(source: string, start: number): OpeningTag | null {
  const head = /^<[A-Za-z][\w.]*/.exec(source.slice(start));
  if (!head) return null;
  const attributes: JsxAttribute[] = [];
  let index = start + head[0].length;
  while (index < source.length) {
    while (/\s/.test(source[index] ?? "")) index += 1;
    const char = source[index];
    if (char === ">") return { attributes, insertAt: index };
    if (char === "/" && source[index + 1] === ">")
      return { attributes, insertAt: index };
    if (char === "{") {
      const end = skipBraces(source, index);
      attributes.push({ name: null, start: index, end });
      index = end;
      continue;
    }
    const name = /^[A-Za-z_$][\w:.-]*/.exec(source.slice(index));
    if (!name) return null;
    const attributeStart = index;
    index += name[0].length;
    if (source[index] === "=") {
      index += 1;
      const value = source[index];
      if (value === '"' || value === "'")
        index = skipQuoted(source, index, value);
      else if (value === "{") index = skipBraces(source, index);
      else return null;
    }
    attributes.push({ name: name[0], start: attributeStart, end: index });
  }
  return null;
}

export function setJsxAttributes(
  files: SourceFiles,
  range: SourceRange,
  values: BlockPropsRecord,
): SourceFiles {
  const source = files[range.file];
  if (source === undefined) return files;
  const tag = scanOpeningTag(source, range.start);
  if (!tag || tag.insertAt > range.end) return files;
  const edits: Array<{ start: number; end: number; text: string }> = [];
  const appended: string[] = [];
  for (const [name, value] of Object.entries(values)) {
    const existing = tag.attributes.find(
      (attribute) => attribute.name === name,
    );
    if (value === undefined) {
      if (!existing) continue;
      let start = existing.start;
      while (start > 0 && /[ \t]/.test(source[start - 1] ?? "")) start -= 1;
      edits.push({ start, end: existing.end, text: "" });
      continue;
    }
    const text = jsxAttribute(name, value) ?? `${name}=""`;
    if (existing)
      edits.push({ start: existing.start, end: existing.end, text });
    else appended.push(text);
  }
  if (appended.length > 0) {
    const before = source[tag.insertAt - 1] ?? "";
    const lead = /\s/.test(before) ? "" : " ";
    const tail = source[tag.insertAt] === "/" ? " " : "";
    edits.push({
      start: tag.insertAt,
      end: tag.insertAt,
      text: `${lead}${appended.join(" ")}${tail}`,
    });
  }
  if (edits.length === 0) return files;
  let next = source;
  for (const edit of edits.sort((a, b) => b.start - a.start)) {
    next = next.slice(0, edit.start) + edit.text + next.slice(edit.end);
  }
  return { ...files, [range.file]: next };
}

export function updateBlockProps(
  files: SourceFiles,
  range: SourceRange,
  previous: Record<string, unknown>,
  props: BlockPropsRecord,
): SourceFiles {
  const values: BlockPropsRecord = { ...props };
  for (const name of Object.keys(previous)) {
    if (name !== "blockId" && !(name in props)) values[name] = undefined;
  }
  return setJsxAttributes(files, range, values);
}

export function replaceElementText(
  files: SourceFiles,
  range: SourceRange,
  text: string,
): SourceFiles {
  const current = rangeText(files, range);
  const match = /^(<[a-z][a-z0-9]*\b[^>]*>)([^<{}]*)(<\/[a-z][a-z0-9]*>)$/.exec(
    current,
  );
  if (!match) return files;
  const safe = text.replace(/[{}<>]/g, "");
  return replaceRange(files, range, `${match[1]}${safe}${match[3]}`);
}

export function blockRanges(
  files: SourceFiles,
  file: string,
  group: BlockGroup,
): SourceRange[] {
  const source = files[file];
  const components = BLOCK_DEFINITIONS.flatMap((definition) =>
    definition.group === group && definition.component
      ? [definition.component]
      : [],
  );
  if (source === undefined || components.length === 0) return [];
  const element = new RegExp(`<(?:${components.join("|")})\\b[^>]*/>`, "g");
  return Array.from(source.matchAll(element), (match) => ({
    file,
    start: match.index,
    end: match.index + match[0].length,
  }));
}

export function isJsxRange(files: SourceFiles, range: SourceRange): boolean {
  const text = rangeText(files, range);
  return text.startsWith("<") && text.endsWith(">");
}

export function placeableTarget(
  entry: { files: SourceFiles; rootSource: SourceRange | null },
  target: SourceDropTarget,
): boolean {
  if (!isJsxRange(entry.files, target)) return false;
  const root = entry.rootSource;
  if (!root || root.file !== target.file) return true;
  if (target.start === root.start && target.end === root.end)
    return target.place === "inside";
  return !(target.start <= root.start && target.end >= root.end);
}
