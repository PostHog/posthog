#!/usr/bin/env tsx

import { execSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

// Anchor to apps/code so the relative paths below (and the pnpm binary lookup)
// resolve the same way no matter which directory the script is invoked from.
process.chdir(path.resolve(path.dirname(fileURLToPath(import.meta.url)), ".."));

const REPO_ROOT = path.resolve(process.cwd(), "../../../..");
// The schema `hogli build:openapi-schema` writes, which every other generator in the repo
// reads. Reading it here rather than fetching a running instance keeps this client pinned to
// the checkout, so a stale regeneration is a diff rather than a silent mismatch.
const OPENAPI_PATH = path.resolve(REPO_ROOT, "frontend/tmp/openapi.json");
const TEMP_SCHEMA_PATH = "temp-openapi.json";
const OUTPUT_PATH = "../../packages/api-client/src/generated.ts";

// Only the endpoints the desktop calls through the typed client are generated. The full
// schema documents thousands of routes, and every backend change to any of them would
// otherwise churn generated.ts; an allowlist keeps a regen to the routes we actually use.
const ALLOWLIST_PATH = "../../packages/api-client/endpoint-allowlist.json";

function readSchema() {
  console.log(`Reading OpenAPI schema from ${OPENAPI_PATH}...`);

  if (!fs.existsSync(OPENAPI_PATH)) {
    console.error(
      `OpenAPI schema not found at ${OPENAPI_PATH}. Run \`hogli build:openapi-schema\` first.`,
    );
    return false;
  }

  try {
    const schema = JSON.parse(fs.readFileSync(OPENAPI_PATH, "utf-8"));

    filterEndpoints(schema);

    fs.writeFileSync(TEMP_SCHEMA_PATH, JSON.stringify(schema), "utf-8");
    console.log(`✓ Schema saved to ${TEMP_SCHEMA_PATH}`);

    return true;
  } catch (error) {
    console.error("Error reading schema:", error);
    return false;
  }
}

interface Allowlist {
  paths: string[];
  schemas: string[];
}

function readAllowlist(): Allowlist {
  const allowlist = JSON.parse(fs.readFileSync(ALLOWLIST_PATH, "utf-8")) as {
    paths?: unknown;
    schemas?: unknown;
  };
  const isStringList = (value: unknown): value is string[] =>
    Array.isArray(value) && value.every((item) => typeof item === "string");
  if (!isStringList(allowlist.paths) || !isStringList(allowlist.schemas)) {
    throw new Error(
      `${ALLOWLIST_PATH} must contain "paths" and "schemas" arrays of strings`,
    );
  }
  return { paths: allowlist.paths, schemas: allowlist.schemas };
}

type Components = Record<string, Record<string, unknown>>;

const REF_PREFIX = "#/components/";

/** Every `$ref` reachable from `value`, as [componentKind, name] pairs. */
function collectRefs(value: unknown, into: Set<string>): void {
  if (Array.isArray(value)) {
    for (const item of value) collectRefs(item, into);
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (
      key === "$ref" &&
      typeof child === "string" &&
      child.startsWith(REF_PREFIX)
    ) {
      into.add(child.slice(REF_PREFIX.length));
    } else {
      collectRefs(child, into);
    }
  }
}

/**
 * Keeps only the component schemas reachable from the kept paths and the
 * allowlisted schema names, following `$ref`s transitively (through other
 * component kinds too, since a shared parameter can reference a schema).
 */
function pruneSchemas(
  schema: { paths?: Record<string, unknown>; components?: Components },
  seeds: string[],
) {
  const components = schema.components;
  if (!components?.schemas) return;

  const missing = seeds.filter((name) => !(name in components.schemas));
  if (missing.length > 0) {
    throw new Error(
      `Allowlisted schemas missing from the schema (remove them from ${ALLOWLIST_PATH} or fix the name):\n  ${missing.join("\n  ")}`,
    );
  }

  const pending = new Set<string>(seeds.map((name) => `schemas/${name}`));
  collectRefs(schema.paths, pending);
  const kept = new Set<string>();
  while (pending.size > 0) {
    const [ref] = pending;
    pending.delete(ref);
    if (kept.has(ref)) continue;
    kept.add(ref);
    const [kind, ...rest] = ref.split("/");
    const definition = components[kind]?.[rest.join("/")];
    const refs = new Set<string>();
    collectRefs(definition, refs);
    for (const next of refs) if (!kept.has(next)) pending.add(next);
  }

  const total = Object.keys(components.schemas).length;
  components.schemas = Object.fromEntries(
    Object.entries(components.schemas).filter(([name]) =>
      kept.has(`schemas/${name}`),
    ),
  );
  console.log(
    `✓ Kept ${Object.keys(components.schemas).length} component schemas of ${total} in the schema`,
  );
}

function filterEndpoints(schema: {
  paths?: Record<string, unknown>;
  components?: Components;
}) {
  if (!schema.paths) return;

  const allowlist = readAllowlist();
  const totalInSchema = Object.keys(schema.paths).length;
  const filteredPaths: Record<string, unknown> = {};
  const missing: string[] = [];

  for (const path of allowlist.paths) {
    const pathItem = schema.paths[path];
    if (pathItem === undefined) {
      missing.push(path);
      continue;
    }
    filteredPaths[path] = pathItem;
  }

  // A path that left the schema means a route was removed or renamed upstream. Failing
  // here names it, instead of a typecheck error at whichever call site used it.
  if (missing.length > 0) {
    throw new Error(
      `Allowlisted endpoints missing from the schema (remove them from ${ALLOWLIST_PATH} or fix the path):\n  ${missing.join("\n  ")}`,
    );
  }

  schema.paths = filteredPaths;
  console.log(
    `✓ Kept ${Object.keys(filteredPaths).length} allowlisted endpoints of ${totalInSchema} in the schema`,
  );
  pruneSchemas(schema, allowlist.schemas);
}

function generateClient() {
  console.log("Generating TypeScript client...");

  try {
    execSync(`pnpm typed-openapi ${TEMP_SCHEMA_PATH} --output ${OUTPUT_PATH}`, {
      stdio: "inherit",
    });
    console.log(`✓ Client generated at ${OUTPUT_PATH}`);
    return true;
  } catch (error) {
    console.error("Error generating client:", error);
    return false;
  }
}

// typed-openapi emits long single-line types. Formatting the output makes a regen diff show
// the types that changed instead of rewrapping the whole file, and matches how the
// checked-in file has always been formatted. Biome skips this file, so prettier does it.
function formatClient() {
  console.log("Formatting generated client...");
  try {
    execSync(`pnpm prettier --write ${OUTPUT_PATH} --log-level warn`, {
      stdio: "inherit",
    });
    console.log("✓ Client formatted");
    return true;
  } catch (error) {
    console.error("Error formatting client:", error);
    return false;
  }
}

function cleanup() {
  try {
    if (fs.existsSync(TEMP_SCHEMA_PATH)) {
      fs.unlinkSync(TEMP_SCHEMA_PATH);
      console.log("✓ Cleaned up temporary schema file");
    }
  } catch (error) {
    console.error("Warning: Could not clean up temporary file:", error);
  }
}

async function main() {
  console.log("Starting OpenAPI client update...\n");

  const schemaRead = readSchema();
  if (!schemaRead) {
    process.exit(1);
  }

  const clientGenerated = generateClient() && formatClient();

  cleanup();

  if (!clientGenerated) {
    process.exit(1);
  }

  console.log("\n✅ OpenAPI client successfully updated!");
}

main().catch((error) => {
  console.error("Unexpected error:", error);
  process.exit(1);
});
