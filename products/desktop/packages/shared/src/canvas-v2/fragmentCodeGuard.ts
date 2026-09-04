import { CANVAS_PLATFORM_MANIFEST } from "../canvas-platform";

export const CANVAS_V2_ALLOWED_IMPORTS: ReadonlySet<string> = new Set([
  ...CANVAS_PLATFORM_MANIFEST.allowedImportSpecifiers,
  "react/jsx-runtime",
  "react/jsx-dev-runtime",
]);

export interface FragmentCodeCheck {
  ok: boolean;
  violations: string[];
}

const FORBIDDEN_CALLS: { re: RegExp; reason: string }[] = [
  { re: /\bimport\s*\(/, reason: "import() is not allowed" },
  { re: /\brequire\s*\(/, reason: "require() is not allowed" },
  { re: /\bimportScripts\s*\(/, reason: "importScripts() is not allowed" },
  { re: /\beval\s*\(/, reason: "eval() is not allowed" },
  { re: /\bnew\s+Function\s*\(/, reason: "new Function() is not allowed" },
  { re: /\bimport\s*\.\s*meta\b/, reason: "import.meta is not allowed" },
];

const MODULE_STATEMENT = /^[ \t]*(import|export)\b/gm;
const QUOTED = /["']([^"'\n]*)["']/;
const STATEMENT_SCAN_LIMIT = 2000;

export function checkFragmentCode(code: string): FragmentCodeCheck {
  const bare = withoutStringsAndComments(code);
  const violations: string[] = [];

  for (const { re, reason } of FORBIDDEN_CALLS) {
    if (re.test(bare)) violations.push(reason);
  }

  for (const specifier of moduleSources(code, bare)) {
    if (!CANVAS_V2_ALLOWED_IMPORTS.has(specifier)) {
      violations.push(`"${specifier}" is not an allowed import`);
    }
  }

  return { ok: violations.length === 0, violations };
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
