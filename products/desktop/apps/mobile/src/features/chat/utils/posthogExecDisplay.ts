/**
 * Mirrors the desktop PostHog MCP exec display logic so mobile unwraps the
 * dispatched sub-tool instead of showing the raw `exec` transport wrapper.
 *
 * Supported verbs:
 *   tools
 *   search <regex>
 *   info <tool>
 *   schema <tool> [field_path]
 *   call [--json] <tool> <json_input>
 */

const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/;

const POSTHOG_VERB_RE =
  /^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/;
const POSTHOG_CALL_BODY_RE = /^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/;
const POSTHOG_TOOL_NAME_RE = /^([a-zA-Z0-9_-]+)\s*([\s\S]*)$/;

export interface PostHogExecDisplay {
  label: string;
  input?: string;
}

export function isPostHogExecTool(toolName: string): boolean {
  return POSTHOG_EXEC_TOOL_RE.test(toolName);
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
      return { label: "List tools", input: undefined };

    case "search":
      return {
        label: "Search tools",
        input: explicitInput ?? (rest.length > 0 ? rest : undefined),
      };

    case "info":
      return rest.length > 0
        ? { label: `Read ${rest}`, input: undefined }
        : { label: "Read tool", input: undefined };

    case "schema": {
      const match = rest.match(POSTHOG_TOOL_NAME_RE);
      if (!match) return { label: "Inspect schema", input: undefined };
      const subTool = match[1];
      const fieldPath = (match[2] ?? "").trim();
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
      const match = rest.match(POSTHOG_CALL_BODY_RE);
      if (!match) return null;
      const subTool = match[1];
      const args = (match[2] ?? "").trim();
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
    // Not JSON; show the raw input.
  }
  return input;
}
