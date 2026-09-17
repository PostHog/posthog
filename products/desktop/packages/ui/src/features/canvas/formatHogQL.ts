const OPENERS = new Set(["(", "[", "{"]);
const CLOSERS = new Set([")", "]", "}"]);
const LITERAL = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`[^`]*`/g;
const MASK = String.fromCharCode(0);
const MASKED = new RegExp(`${MASK}(\\d+)${MASK}`, "g");

export function wordPattern(words: string): RegExp {
  return new RegExp(`(?<=^|\\s)(?:${words})\\b`, "iy");
}

const CLAUSE = wordPattern(
  "SELECT DISTINCT|SELECT|FROM|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|OFFSET|UNION ALL|LEFT JOIN|INNER JOIN|CROSS JOIN|JOIN|WITH",
);
const CONNECTOR = wordPattern("AND|OR");
export const COMMA = /,/y;

export interface Segment {
  keyword: string;
  body: string;
}

export function maskLiterals(text: string): {
  masked: string;
  literals: string[];
} {
  const literals: string[] = [];
  const masked = text
    .replace(LITERAL, (match) => {
      literals.push(match);
      return `${MASK}${literals.length - 1}${MASK}`;
    })
    .replace(/\s+/g, " ");
  return { masked, literals };
}

export function restoreLiterals(text: string, literals: string[]): string {
  return text.replace(
    MASKED,
    (_, index: string) => literals[Number(index)] ?? "",
  );
}

export function formatHogQL(sql: string): string {
  const source = sql.trim();
  if (!source) return sql;
  const { masked, literals } = maskLiterals(source);
  const rendered = splitClauses(masked).map(renderSegment).join("\n");
  const restored = restoreLiterals(rendered, literals);
  return normalize(restored) === normalize(source) ? restored : sql;
}

function normalize(text: string): string {
  return text.replace(/\s+/g, "").toLowerCase();
}

export function splitOutsideBrackets(text: string, pattern: RegExp): Segment[] {
  const segments: Segment[] = [];
  let current: Segment = { keyword: "", body: "" };
  let depth = 0;
  let index = 0;
  while (index < text.length) {
    pattern.lastIndex = index;
    const match = depth === 0 ? pattern.exec(text) : null;
    if (match) {
      segments.push(current);
      current = { keyword: match[0], body: "" };
      index += match[0].length;
      continue;
    }
    const char = text[index];
    if (OPENERS.has(char)) depth += 1;
    if (CLOSERS.has(char)) depth = Math.max(0, depth - 1);
    current.body += char;
    index += 1;
  }
  segments.push(current);
  return segments.filter((segment) => segment.keyword || segment.body.trim());
}

export function splitOn(text: string, pattern: RegExp): string[] {
  return splitOutsideBrackets(text, pattern)
    .map((segment) => segment.body.trim())
    .filter((body) => body.length > 0);
}

export function splitClauses(text: string): Segment[] {
  return splitOutsideBrackets(text, CLAUSE).map(({ keyword, body }) => ({
    keyword: keyword.toUpperCase(),
    body,
  }));
}

function renderSegment({ keyword, body }: Segment): string {
  const text = body.trim();
  if (!keyword) return text;
  if (keyword.startsWith("SELECT")) {
    const items = splitOn(text, COMMA);
    return items.length > 1 || text.length > 60
      ? `${keyword}\n  ${items.join(",\n  ")}`
      : `${keyword} ${text}`;
  }
  if (keyword === "WHERE" || keyword === "HAVING") {
    const lines = splitOutsideBrackets(text, CONNECTOR).map((segment) =>
      [segment.keyword.toUpperCase(), segment.body.trim()]
        .filter(Boolean)
        .join(" "),
    );
    return `${keyword} ${lines.join("\n  ")}`;
  }
  return `${keyword} ${text}`;
}
