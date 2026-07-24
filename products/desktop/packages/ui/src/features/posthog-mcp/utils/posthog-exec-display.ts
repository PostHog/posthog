/**
 * The PostHog MCP exposes a single `exec` dispatcher that runs CLI-style
 * subcommands. Generic MCP rendering would show this as
 * `posthog - exec (MCP) {"command":"call execute-sql {…}"}` — pure plumbing
 * with the dispatched action buried inside a JSON wrapper.
 *
 * These helpers pull the action out of the `command` string so the row can
 * read `posthog - execute-sql {…}` (call), `posthog - Read execute-sql`
 * (info), `posthog - Inspect query-trends.series` (schema),
 * `posthog - Search tools query-` (search), or `posthog - List tools`
 * (tools) instead.
 *
 * Supported verbs (per the `exec` tool description):
 *   tools                                  — list every tool
 *   search <regex>                         — search by name/title/description
 *   info <tool>                            — show description + input schema
 *   schema <tool> [field_path]             — drill into a specific field
 *   call [--json] <tool> <json_input>      — invoke a tool
 */

import { parseMcpToolName } from "@posthog/shared";

// A PostHog MCP server name: optional `plugin_` prefix, `posthog`, then any
// number of `_<segment>` parts (e.g. `posthog`, `posthog_cloud`,
// `plugin_posthog_posthog`). The `exec` dispatcher lives on these servers.
const POSTHOG_SERVER_RE = /^(?:plugin_)?posthog(?:_[^_]+)*$/;

const POSTHOG_VERB_RE =
  /^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/;
const POSTHOG_CALL_BODY_RE = /^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/;
const POSTHOG_TOOL_NAME_RE = /^([a-zA-Z0-9_-]+)\s*([\s\S]*)$/;

export interface PostHogExecDisplay {
  /** Replaces the tool name in the title — e.g. "execute-sql", "Read execute-sql". */
  label: string;
  /** Args to show as the input preview, undefined when there is none to display. */
  input?: string;
}

export function isPostHogExecTool(toolName: string): boolean {
  const mcp = parseMcpToolName(toolName);
  return !!mcp && mcp.tool === "exec" && POSTHOG_SERVER_RE.test(mcp.server);
}

export function getPostHogExecDisplay(
  toolInput: unknown,
): PostHogExecDisplay | null {
  if (!toolInput || typeof toolInput !== "object") return null;
  const obj = toolInput as { command?: unknown; input?: unknown };

  if (typeof obj.command !== "string") return null;
  const verbMatch = obj.command.match(POSTHOG_VERB_RE);
  if (!verbMatch) return null;

  const verb = verbMatch[1] as "tools" | "search" | "info" | "schema" | "call";
  const rest = (verbMatch[2] ?? "").trim();
  const explicitInput = readExplicitInput(obj.input);

  switch (verb) {
    case "tools":
      // `tools` returns names only, not full schemas — "List", not "Read".
      return { label: "List tools", input: undefined };

    case "search":
      return {
        label: "Search tools",
        input: explicitInput ?? (rest.length > 0 ? rest : undefined),
      };

    case "info":
      // `info <tool>` — fold the tool name into the label so the args slot stays clean.
      return rest.length > 0
        ? { label: `Read ${rest}`, input: undefined }
        : { label: "Read tool", input: undefined };

    case "schema": {
      // `schema <tool> [field_path]` is the drill-down verb. Fold the
      // tool + path into a dotted locator so it reads as one path.
      const m = rest.match(POSTHOG_TOOL_NAME_RE);
      if (!m) return { label: "Inspect schema", input: undefined };
      const subTool = m[1];
      const fieldPath = (m[2] ?? "").trim();
      const path =
        explicitInput ?? (fieldPath.length > 0 ? fieldPath : undefined);
      return {
        label: path
          ? `Inspect ${subTool}.${path}`
          : `Inspect ${subTool} fields`,
        input: undefined,
      };
    }

    case "call": {
      // `call [--json] <tool> [json_input]` — collapse the verb, surface the
      // sub-tool as the label and the JSON body as args.
      const m = rest.match(POSTHOG_CALL_BODY_RE);
      if (!m) return null;
      const subTool = m[1];
      const args = (m[2] ?? "").trim();
      return {
        label: subTool,
        input: explicitInput ?? (args.length > 0 ? args : undefined),
      };
    }
  }
}

function readExplicitInput(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string") return value.trim() || undefined;
  try {
    return JSON.stringify(value);
  } catch {
    return undefined;
  }
}

/**
 * Pretty-prints the unwrapped exec args for display in the permission dialog
 * body — JSON payloads (the `call` case) render multi-line; non-JSON args
 * (e.g. a `search` regex) pass through unchanged.
 */
export function formatPosthogExecBody(
  input: string | undefined,
): string | undefined {
  if (!input) return undefined;
  try {
    const parsed = JSON.parse(input);
    if (parsed && typeof parsed === "object") {
      return JSON.stringify(parsed, null, 2);
    }
  } catch {
    // not JSON — fall through and show raw
  }
  return input;
}
