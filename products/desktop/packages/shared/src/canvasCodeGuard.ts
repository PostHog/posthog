import { CANVAS_PLATFORM_MANIFEST } from "./canvas-platform";

export const CANVAS_BASE_ALLOWED_IMPORTS: ReadonlySet<string> = new Set([
  ...CANVAS_PLATFORM_MANIFEST.allowedImportSpecifiers,
  "react/jsx-runtime",
  "react/jsx-dev-runtime",
]);

export interface CanvasCodeCheck {
  ok: boolean;
  violations: string[];
}

const FORBIDDEN_CALLS: { re: RegExp; reason: string }[] = [
  { re: /\bimport\s*\(/, reason: "import() is not allowed" },
  { re: /\brequire\s*\(/, reason: "require() is not allowed" },
  { re: /\bimportScripts\s*\(/, reason: "importScripts() is not allowed" },
  { re: /\beval\s*\(/, reason: "eval() is not allowed" },
  { re: /\bnew\s+Function\s*\(/, reason: "new Function() is not allowed" },
  { re: /\bFunction\s*\(/, reason: "Function() is not allowed" },
  {
    re: /\.\s*constructor\b/,
    reason: "constructor access is not allowed",
  },
  { re: /\b__proto__\b/, reason: "__proto__ access is not allowed" },
  { re: /\bimport\s*\.\s*meta\b/, reason: "import.meta is not allowed" },
];

// Members that give arbitrary code execution to code that reaches them.
// `constructor` is in the set because it leads to the Function constructor from
// any value.
const FORBIDDEN_MEMBERS: ReadonlySet<string> = new Set([
  "eval",
  "Function",
  "require",
  "importScripts",
  "constructor",
  "__proto__",
]);

const MODULE_STATEMENT = /\b(import|export)\b/g;
const QUOTED = /["']([^"'\n]*)["']/;
const STATEMENT_SCAN_LIMIT = 2000;

// A static pre-filter, not a security boundary. It rejects the plain routes to
// dynamic code and to modules outside the allowlist, and it reads member keys
// that the code builds from literal text, so `x["ev" + "al"]` is rejected. A key
// that exists only at run time, such as `x[name]`, can still name any member, so
// the frame CSP stays the boundary: `default-src 'none'`, no `unsafe-eval`, and
// no network egress.
export function checkCanvasCode(
  code: string,
  allowed: ReadonlySet<string> = CANVAS_BASE_ALLOWED_IMPORTS,
): CanvasCodeCheck {
  const bare = withoutStringsAndComments(code);
  const violations: string[] = [];
  if (/<script\b/i.test(code))
    violations.push("inline <script> is not allowed");

  for (const { re, reason } of FORBIDDEN_CALLS) {
    if (re.test(bare)) violations.push(reason);
  }

  for (const key of constantMemberKeys(code, bare)) {
    if (FORBIDDEN_MEMBERS.has(key)) {
      violations.push(`member access to "${key}" is not allowed`);
    }
  }

  for (const specifier of moduleSources(code, bare)) {
    if (!allowed.has(specifier)) {
      violations.push(`import of non-whitelisted module "${specifier}"`);
    }
  }

  return { ok: violations.length === 0, violations };
}

function constantMemberKeys(code: string, bare: string): string[] {
  const keys: string[] = [];
  for (let i = 0; i < bare.length; i += 1) {
    if (bare[i] !== "[") continue;
    const close = closingBracket(bare, i);
    if (close === -1) continue;
    const key = constantText(code.slice(i + 1, close));
    if (key !== null) keys.push(key);
  }
  return keys;
}

function closingBracket(bare: string, open: number): number {
  let depth = 0;
  for (let i = open; i < bare.length; i += 1) {
    if (bare[i] === "[") depth += 1;
    else if (bare[i] === "]") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

// Reads text that is built only from literals, so `"ev" + "al"` reads as
// `eval`. Text that needs a value at run time has no constant form and gives
// null.
function constantText(text: string): string | null {
  const parts: string[] = [];
  let rest = text.trim();

  while (rest.length > 0) {
    const literal = /^(["'`])((?:\\.|(?!\1)[^\\])*)\1/.exec(rest);
    if (!literal) return null;
    const body = literal[2] ?? "";
    if (literal[1] === "`" && body.includes("${")) return null;
    parts.push(unescapeLiteral(body));
    rest = rest.slice(literal[0].length).trim();
    if (rest.length === 0) break;
    if (rest[0] !== "+") return null;
    rest = rest.slice(1).trim();
  }

  return parts.length > 0 ? parts.join("") : null;
}

function unescapeLiteral(body: string): string {
  return body.replace(
    /\\(?:u\{([0-9a-fA-F]+)\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|(.))/gs,
    (
      _match,
      braced?: string,
      unicode?: string,
      hex?: string,
      char?: string,
    ) => {
      const point = braced ?? unicode ?? hex;
      if (point !== undefined) return String.fromCodePoint(parseInt(point, 16));
      return char ?? "";
    },
  );
}

function moduleSources(code: string, bare: string): string[] {
  const sources: string[] = [];
  for (const match of bare.matchAll(MODULE_STATEMENT)) {
    const from = match.index ?? 0;
    const end = statementEnd(bare, from);
    const head = bare.slice(from, end);
    if (match[1] === "export" && !/\bfrom\b/.test(head)) continue;
    const quoted = QUOTED.exec(code.slice(from, end));
    if (quoted) sources.push(quoted[1] ?? "");
  }
  return sources;
}

function statementEnd(bare: string, from: number): number {
  const limit = Math.min(bare.length, from + STATEMENT_SCAN_LIMIT);
  const semicolon = bare.indexOf(";", from);
  return semicolon === -1 || semicolon > limit ? limit : semicolon;
}

function withoutStringsAndComments(code: string): string {
  const out = code.split("");
  const blank = (from: number, to: number): void => {
    for (let i = from; i < to && i < out.length; i += 1) {
      if (out[i] !== "\n") out[i] = " ";
    }
  };
  const templateHoles: number[] = [];
  let inTemplate = false;
  let i = 0;

  while (i < code.length) {
    const char = code[i];
    const next = code[i + 1];

    if (inTemplate) {
      if (char === "\\") {
        blank(i, i + 2);
        i += 2;
        continue;
      }
      if (char === "`") {
        blank(i, i + 1);
        inTemplate = false;
        i += 1;
        continue;
      }
      if (char === "$" && next === "{") {
        blank(i, i + 2);
        templateHoles.push(0);
        inTemplate = false;
        i += 2;
        continue;
      }
      blank(i, i + 1);
      i += 1;
      continue;
    }

    if (char === "/" && next === "/") {
      const end = indexOrEnd(code, "\n", i);
      blank(i, end);
      i = end;
      continue;
    }
    if (char === "/" && next === "*") {
      const end = code.indexOf("*/", i + 2);
      const stop = end === -1 ? code.length : end + 2;
      blank(i, stop);
      i = stop;
      continue;
    }
    if (char === '"' || char === "'") {
      const end = endOfQuoted(code, i, char);
      blank(i, end);
      i = end;
      continue;
    }
    if (char === "`") {
      blank(i, i + 1);
      inTemplate = true;
      i += 1;
      continue;
    }
    if (templateHoles.length > 0 && (char === "{" || char === "}")) {
      const depth = templateHoles[templateHoles.length - 1] ?? 0;
      if (char === "{") {
        templateHoles[templateHoles.length - 1] = depth + 1;
      } else if (depth > 0) {
        templateHoles[templateHoles.length - 1] = depth - 1;
      } else {
        templateHoles.pop();
        blank(i, i + 1);
        inTemplate = true;
      }
      i += 1;
      continue;
    }
    i += 1;
  }
  return out.join("");
}

function indexOrEnd(code: string, needle: string, from: number): number {
  const at = code.indexOf(needle, from);
  return at === -1 ? code.length : at;
}

function endOfQuoted(code: string, start: number, quote: string): number {
  let i = start + 1;
  while (i < code.length) {
    const char = code[i];
    if (char === "\n") return i;
    if (char === "\\") {
      i += 2;
      continue;
    }
    if (char === quote) return i + 1;
    i += 1;
  }
  return code.length;
}
