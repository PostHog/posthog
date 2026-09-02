import { parseMcpToolName } from "@posthog/shared";

const POSTHOG_SERVER_RE = /^(?:plugin_)?posthog(?:_[^_]+)*$/;
const POSTHOG_VERB_RE =
  /^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/;
const POSTHOG_CALL_BODY_RE = /^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/;
const POSTHOG_TOOL_NAME_RE = /^([a-zA-Z0-9_-]+)\s*([\s\S]*)$/;

export interface PostHogExecDisplay {
  label: string;
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
  const input = toolInput as { command?: unknown; input?: unknown };
  if (typeof input.command !== "string") return null;
  const match = input.command.match(POSTHOG_VERB_RE);
  if (!match) return null;
  const verb = match[1] as "tools" | "search" | "info" | "schema" | "call";
  const rest = (match[2] ?? "").trim();
  const explicitInput = readExplicitInput(input.input);

  switch (verb) {
    case "tools":
      return { label: "List tools", input: undefined };
    case "search":
      return {
        label: "Search tools",
        input: explicitInput ?? (rest || undefined),
      };
    case "info":
      return { label: rest ? `Read ${rest}` : "Read tool", input: undefined };
    case "schema": {
      const schema = rest.match(POSTHOG_TOOL_NAME_RE);
      if (!schema) return { label: "Inspect schema", input: undefined };
      const path = explicitInput ?? ((schema[2] ?? "").trim() || undefined);
      return {
        label: path
          ? `Inspect ${schema[1]}.${path}`
          : `Inspect ${schema[1]} fields`,
        input: undefined,
      };
    }
    case "call": {
      const call = rest.match(POSTHOG_CALL_BODY_RE);
      if (!call) return null;
      return {
        label: call[1],
        input: explicitInput ?? ((call[2] ?? "").trim() || undefined),
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

export function formatPosthogExecBody(
  input: string | undefined,
): string | undefined {
  if (!input) return undefined;
  try {
    const parsed = JSON.parse(input);
    if (parsed && typeof parsed === "object")
      return JSON.stringify(parsed, null, 2);
  } catch {
    return input;
  }
  return input;
}
