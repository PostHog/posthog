const CLAUSE =
  /^(SELECT DISTINCT|SELECT|FROM|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|OFFSET|UNION ALL|LEFT JOIN|INNER JOIN|CROSS JOIN|JOIN|WITH)\b/i;
const CONNECTOR = /^(AND|OR)\b/i;
const OPENERS = new Set(["(", "[", "{"]);
const CLOSERS = new Set([")", "]", "}"]);
const LITERAL = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`[^`]*`/g;
const MASK = String.fromCharCode(0);
const MASKED = new RegExp(`${MASK}(\\d+)${MASK}`, "g");

interface Segment {
  keyword: string;
  body: string;
}

export function formatHogQL(sql: string): string {
  const source = sql.trim();
  if (!source) return sql;
  const literals: string[] = [];
  const masked = source
    .replace(LITERAL, (match) => {
      literals.push(match);
      return `${MASK}${literals.length - 1}${MASK}`;
    })
    .replace(/\s+/g, " ");
  const rendered = splitClauses(masked).map(renderSegment).join("\n");
  const restored = rendered.replace(
    MASKED,
    (_, index: string) => literals[Number(index)] ?? "",
  );
  return normalize(restored) === normalize(source) ? restored : sql;
}

function normalize(text: string): string {
  return text.replace(/\s+/g, "").toLowerCase();
}

function splitClauses(text: string): Segment[] {
  const segments: Segment[] = [];
  let current: Segment = { keyword: "", body: "" };
  let depth = 0;
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    const atWordStart = index === 0 || text[index - 1] === " ";
    if (depth === 0 && atWordStart) {
      const match = CLAUSE.exec(text.slice(index));
      if (match) {
        if (current.keyword || current.body.trim()) segments.push(current);
        current = { keyword: match[1].toUpperCase(), body: "" };
        index += match[1].length;
        continue;
      }
    }
    if (OPENERS.has(char)) depth += 1;
    if (CLOSERS.has(char)) depth = Math.max(0, depth - 1);
    current.body += char;
    index += 1;
  }
  segments.push(current);
  return segments;
}

function renderSegment({ keyword, body }: Segment): string {
  const text = body.trim();
  if (!keyword) return text;
  if (keyword.startsWith("SELECT")) {
    const items = splitTopLevel(text, ",");
    return items.length > 1 || text.length > 60
      ? `${keyword}\n  ${items.join(",\n  ")}`
      : `${keyword} ${text}`;
  }
  if (keyword === "WHERE" || keyword === "HAVING") {
    return `${keyword} ${splitConnectors(text).join("\n  ")}`;
  }
  return `${keyword} ${text}`;
}

function splitTopLevel(text: string, separator: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (OPENERS.has(char)) depth += 1;
    if (CLOSERS.has(char)) depth = Math.max(0, depth - 1);
    if (depth === 0 && char === separator) {
      parts.push(text.slice(start, index).trim());
      start = index + 1;
    }
  }
  parts.push(text.slice(start).trim());
  return parts.filter((part) => part.length > 0);
}

function splitConnectors(text: string): string[] {
  const lines: string[] = [];
  let depth = 0;
  let start = 0;
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    if (OPENERS.has(char)) depth += 1;
    if (CLOSERS.has(char)) depth = Math.max(0, depth - 1);
    const atWordStart = index > 0 && text[index - 1] === " ";
    if (depth === 0 && atWordStart) {
      const match = CONNECTOR.exec(text.slice(index));
      if (match) {
        lines.push(text.slice(start, index).trim());
        start = index;
        index += match[1].length;
        continue;
      }
    }
    index += 1;
  }
  lines.push(text.slice(start).trim());
  return lines
    .filter((line) => line.length > 0)
    .map((line) => line.replace(CONNECTOR, (word) => word.toUpperCase()));
}
