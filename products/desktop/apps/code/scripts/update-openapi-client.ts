#!/usr/bin/env tsx

import { execSync } from "node:child_process";
import * as fs from "node:fs";
import { config } from "dotenv";
import * as yaml from "yaml";

config();

const POSTHOG_API_HOST = process.env.VITE_POSTHOG_API_HOST;
if (!POSTHOG_API_HOST) {
  throw new Error("VITE_POSTHOG_API_HOST environment variable is required");
}

const SCHEMA_URL = `${POSTHOG_API_HOST}/api/schema/`;
const TEMP_SCHEMA_PATH = "temp-openapi.yaml";
const OUTPUT_PATH = "src/renderer/api/generated.ts";

const INCLUDED_ENDPOINT_PREFIXES = [
  "/api/projects/{project_id}/tasks",
  "/api/users/",
  "/api/environments/",
  "/api/projects/",
];

async function fetchSchema() {
  console.log("Fetching OpenAPI schema from PostHog API...");

  try {
    const response = await fetch(SCHEMA_URL);
    if (!response.ok) {
      throw new Error(
        `Failed to fetch schema: ${response.status} ${response.statusText}`,
      );
    }

    const schemaText = await response.text();
    const schema = yaml.parse(schemaText);

    filterEndpoints(schema);

    fs.writeFileSync(TEMP_SCHEMA_PATH, yaml.stringify(schema), "utf-8");
    console.log(`✓ Schema saved to ${TEMP_SCHEMA_PATH}`);

    return true;
  } catch (error) {
    console.error("Error fetching schema:", error);
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

  const schemaFetched = await fetchSchema();
  if (!schemaFetched) {
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
