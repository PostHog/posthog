/**
 * Standalone stdio MCP server exposing the general local tools to the Codex
 * app-server adapter, which spawns it as an MCP server process. Reads its context
 * (cwd, taskId, token) from POSTHOG_LOCAL_TOOLS_CTX and the set of tools to
 * register from POSTHOG_LOCAL_TOOLS_ENABLED (both set by the parent, which has
 * already evaluated each tool's gate) — then registers those registry tools,
 * the same ones the Claude adapter exposes in-process.
 *
 * Usage:
 *   POSTHOG_LOCAL_TOOLS_CTX=<base64> \
 *   POSTHOG_LOCAL_TOOLS_ENABLED=git_signed_commit \
 *     node local-tools-mcp-server.js
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { readGithubTokenFromEnv } from "@posthog/git/signed-commit";
import {
  LOCAL_TOOLS,
  LOCAL_TOOLS_MCP_NAME,
  type LocalToolCtx,
} from "../local-tools";

function die(message: string): never {
  process.stderr.write(`[local-tools-mcp-server] ${message}\n`);
  process.exit(1);
}

const ctxEnv = process.env.POSTHOG_LOCAL_TOOLS_CTX;
if (!ctxEnv) {
  die("POSTHOG_LOCAL_TOOLS_CTX env var is required");
}

let parsed: {
  cwd: string;
  taskId?: string;
  token?: string;
  baseBranch?: string;
};
try {
  parsed = JSON.parse(Buffer.from(ctxEnv, "base64").toString("utf-8"));
} catch (err) {
  die(`Failed to parse POSTHOG_LOCAL_TOOLS_CTX as base64-encoded JSON: ${err}`);
}

if (!parsed.cwd) {
  die("POSTHOG_LOCAL_TOOLS_CTX must include cwd");
}

const ctx: LocalToolCtx = {
  cwd: parsed.cwd,
  token: parsed.token ?? readGithubTokenFromEnv(),
  taskId: parsed.taskId,
  baseBranch: parsed.baseBranch,
};

const enabledNames = (process.env.POSTHOG_LOCAL_TOOLS_ENABLED ?? "")
  .split(",")
  .filter(Boolean);
const tools = LOCAL_TOOLS.filter((t) => enabledNames.includes(t.name));
if (tools.length === 0) {
  die("POSTHOG_LOCAL_TOOLS_ENABLED listed no known tools");
}

const server = new McpServer({
  name: LOCAL_TOOLS_MCP_NAME,
  version: "1.0.0",
});

for (const t of tools) {
  server.tool(t.name, t.description, t.schema, async (args) =>
    t.handler(ctx, args),
  );
}

const transport = new StdioServerTransport();
await server.connect(transport);
