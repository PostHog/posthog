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

const INCLUDED_ENDPOINT_PREFIXES = [
  "/api/projects/{project_id}/tasks",
  "/api/users/",
  "/api/environments/",
  "/api/projects/",
];

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

function filterEndpoints(schema: { paths?: Record<string, unknown> }) {
  if (!schema.paths) return;

  const filteredPaths: Record<string, unknown> = {};

  for (const [path, pathItem] of Object.entries(schema.paths)) {
    if (INCLUDED_ENDPOINT_PREFIXES.some((prefix) => path.startsWith(prefix))) {
      filteredPaths[path] = pathItem;
    }
  }

  schema.paths = filteredPaths;
  console.log(`✓ Filtered to ${Object.keys(filteredPaths).length} endpoints`);
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

  const clientGenerated = generateClient();

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
