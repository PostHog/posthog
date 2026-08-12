import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Guards against the Symbol.for collision class: `Symbol.for(key)` resolves
// through the global registry, so two token consts in different files (even
// different packages, with different export names) that pass the SAME string
// are the SAME symbol. Binding two different services to it is last-load-wins
// with no error — the wrong service resolves (e.g. "r.connect is not a
// function"). Every DI token string must therefore be defined in exactly one
// production source file.

const repoRoot = fileURLToPath(new URL("../../..", import.meta.url));
const SCAN_ROOTS = ["packages", "apps"];
const SKIP_DIRS = new Set([
  "node_modules",
  "dist",
  "build",
  "out",
  ".vite",
  ".turbo",
  "coverage",
]);
const SOURCE_RE = /\.tsx?$/;
// Tests legitimately re-declare a real token's string to match it in a fake
// container; stories and type decls are not bindings.
const EXCLUDE_FILE_RE = /\.(test|spec|stories)\.tsx?$|\.d\.ts$/;
const SYMBOL_FOR_RE = /Symbol\.for\(\s*["']([^"']+)["']/g;
const NAMED_TOKEN_RE =
  /const\s+([A-Z][A-Z0-9_]*)\s*=\s*Symbol\.for\(\s*["']([^"']+)["']/g;

function collectSourceFiles(dir: string, acc: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      collectSourceFiles(join(dir, entry.name), acc);
    } else if (
      SOURCE_RE.test(entry.name) &&
      !EXCLUDE_FILE_RE.test(entry.name)
    ) {
      acc.push(join(dir, entry.name));
    }
  }
}

interface TokenSite {
  file: string;
  name: string;
}

function findTokenStrings(): Map<string, TokenSite[]> {
  const files: string[] = [];
  for (const root of SCAN_ROOTS) {
    collectSourceFiles(join(repoRoot, root), files);
  }

  const byString = new Map<string, TokenSite[]>();
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    if (!text.includes("Symbol.for(")) continue;

    const names = new Map<string, string>();
    for (const match of text.matchAll(NAMED_TOKEN_RE)) {
      names.set(match[2], match[1]);
    }

    const relative = file.slice(repoRoot.length);
    for (const match of text.matchAll(SYMBOL_FOR_RE)) {
      const key = match[1];
      const sites = byString.get(key) ?? [];
      sites.push({ file: relative, name: names.get(key) ?? "(unnamed)" });
      byString.set(key, sites);
    }
  }
  return byString;
}

describe("DI token Symbol.for uniqueness", () => {
  it("never defines the same Symbol.for string in more than one source file", () => {
    const byString = findTokenStrings();

    const collisions = [...byString.entries()].filter(([, sites]) => {
      const distinctFiles = new Set(sites.map((s) => s.file));
      return distinctFiles.size > 1;
    });

    const report = collisions
      .map(([key, sites]) => {
        const lines = sites.map((s) => `    ${s.name} @ ${s.file}`).join("\n");
        return `  Symbol.for("${key}") is defined in multiple files:\n${lines}`;
      })
      .join("\n\n");

    expect(
      collisions.length,
      collisions.length === 0
        ? ""
        : `Duplicate DI token string(s) found — these resolve to the SAME symbol and will silently shadow each other. Namespace them distinctly (posthog.<area>.<thing>):\n\n${report}\n`,
    ).toBe(0);
  });
});
