import { statSync } from "node:fs";
import * as path from "node:path";
import type { Capture } from "./ast-helpers.js";
import { getCapture } from "./ast-helpers.js";
import type { ParserManager } from "./parser-manager.js";
import type { ImportEdge } from "./types.js";

const JS_EXTENSION_PROBES = [
  ".ts",
  ".tsx",
  ".mts",
  ".cts",
  ".js",
  ".jsx",
  ".mjs",
  ".cjs",
];

const PY_EXTENSION_PROBES = [".py"];

function isRelativeSpecifier(spec: string): boolean {
  return spec.startsWith("./") || spec.startsWith("../") || spec === ".";
}

function resolveJsPath(
  callerAbsPath: string,
  specifier: string,
): string | null {
  if (!isRelativeSpecifier(specifier)) return null;

  const dir = path.dirname(callerAbsPath);
  const base = path.resolve(dir, specifier);

  // If the specifier already includes a concrete supported file extension,
  // try that exact path first before probing extension variants.
  if (JS_EXTENSION_PROBES.includes(path.extname(specifier))) {
    return isFile(base) ? base : null;
  }

  if (isFile(base)) return base;

  for (const ext of JS_EXTENSION_PROBES) {
    const candidate = base + ext;
    if (isFile(candidate)) return candidate;
  }

  for (const ext of JS_EXTENSION_PROBES) {
    const candidate = path.join(base, `index${ext}`);
    if (isFile(candidate)) return candidate;
  }

  return null;
}

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

function resolvePythonModule(
  callerAbsPath: string,
  relativePrefix: string,
  moduleName: string | null,
): string | null {
  if (!relativePrefix) return null;

  // `.tel` → dots = 1, up 0 levels. `..foo` → dots = 2, up 1 level.
  const dots = relativePrefix.length;
  const levelsUp = dots - 1;

  let baseDir = path.dirname(callerAbsPath);
  for (let i = 0; i < levelsUp; i++) {
    baseDir = path.dirname(baseDir);
  }

  if (!moduleName) {
    const init = path.join(baseDir, "__init__.py");
    return isFile(init) ? init : null;
  }

  const parts = moduleName.split(".");
  const joined = path.join(baseDir, ...parts);

  for (const ext of PY_EXTENSION_PROBES) {
    const candidate = joined + ext;
    if (isFile(candidate)) return candidate;
  }

  const pkgInit = path.join(joined, "__init__.py");
  if (isFile(pkgInit)) return pkgInit;

  return null;
}

export async function findImports(
  pm: ParserManager,
  source: string,
  languageId: string,
  callerAbsPath: string,
): Promise<ImportEdge[]> {
  const ready = await pm.ensureReady(languageId);
  if (!ready) return [];
  const { lang, family } = ready;
  if (!family.queries.imports) return [];

  const tree = pm.parse(source, lang);
  if (!tree) return [];

  const query = pm.getQuery(lang, family.queries.imports);
  if (!query) return [];

  const edges: ImportEdge[] = [];
  const isPython = languageId === "python";

  for (const match of query.matches(tree.rootNode)) {
    if (isPython) {
      pushPythonEdge(match.captures, callerAbsPath, edges);
    } else {
      pushJsEdge(match.captures, callerAbsPath, edges);
    }
  }

  return dedupe(edges);
}

function pushJsEdge(
  captures: Capture[],
  callerAbsPath: string,
  out: ImportEdge[],
): void {
  const sourceNode = getCapture(captures, "source");
  if (!sourceNode) return;
  const specifier = sourceNode.text;
  if (!isRelativeSpecifier(specifier)) return;

  const resolvedAbsPath = resolveJsPath(callerAbsPath, specifier);

  const defaultNode = getCapture(captures, "default_name");
  if (defaultNode) {
    out.push({
      localName: defaultNode.text,
      importedName: "default",
      isDefault: true,
      resolvedAbsPath,
    });
    return;
  }

  const namespaceNode = getCapture(captures, "namespace_name");
  if (namespaceNode) {
    out.push({
      localName: namespaceNode.text,
      importedName: "*",
      isNamespace: true,
      resolvedAbsPath,
    });
    return;
  }

  const importedNode = getCapture(captures, "imported_name");
  if (importedNode) {
    const localNode = getCapture(captures, "local_name");
    out.push({
      localName: (localNode ?? importedNode).text,
      importedName: importedNode.text,
      resolvedAbsPath,
    });
  }
}

function pushPythonEdge(
  captures: Capture[],
  callerAbsPath: string,
  out: ImportEdge[],
): void {
  const importedNode = getCapture(captures, "imported_name");
  if (!importedNode) return;

  const relativePrefix = getCapture(captures, "relative_prefix");
  const relativeName = getCapture(captures, "relative_name");
  const sourceNode = getCapture(captures, "source");

  let resolvedAbsPath: string | null = null;

  if (relativePrefix) {
    resolvedAbsPath = resolvePythonModule(
      callerAbsPath,
      relativePrefix.text,
      relativeName ? relativeName.text : null,
    );
  } else if (sourceNode) {
    // Absolute-style `from tel import track` — v1: only resolve as sibling module.
    resolvedAbsPath = resolvePythonModule(callerAbsPath, ".", sourceNode.text);
  }

  const localNode = getCapture(captures, "local_name");
  out.push({
    localName: (localNode ?? importedNode).text,
    importedName: importedNode.text,
    resolvedAbsPath,
  });
}

function dedupe(edges: ImportEdge[]): ImportEdge[] {
  const seen = new Set<string>();
  const out: ImportEdge[] = [];
  for (const e of edges) {
    const key = `${e.localName}|${e.importedName}|${e.resolvedAbsPath ?? ""}|${e.isDefault ? "d" : ""}|${e.isNamespace ? "n" : ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(e);
  }
  return out;
}
