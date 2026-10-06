import { z } from "zod";
import type {
  AgentToolCallLocation,
  AgentToolCallStatus,
  AgentToolKind,
} from "./agent-conversation";

export const PI_TOOL_KIND_BY_NAME = {
  read: "read",
  edit: "edit",
  write: "edit",
  bash: "execute",
  grep: "search",
  find: "search",
  ls: "list",
} as const satisfies Record<string, AgentToolKind>;

export type PiToolName = keyof typeof PI_TOOL_KIND_BY_NAME;

export interface PiToolCallInput {
  id: string;
  name: string;
  arguments: unknown;
}

export const piMcpCallDetailsSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("search"), query: z.string().min(1) }),
  z.object({
    kind: z.literal("tool"),
    name: z.string().min(1),
    args: z.string().optional(),
  }),
]);
export type PiMcpCallDetails = z.infer<typeof piMcpCallDetailsSchema>;

const piMcpProxyInputSchema = z.object({
  search: z.string().trim().min(1).optional(),
  tool: z.string().trim().min(1).optional(),
  args: z.string().optional(),
});

const posthogExecServerPattern = /^(?:plugin_)?posthog(?:_[^_]+)*$/;

function readPiMcpToolParts(
  name: string,
): { server: string; tool: string } | undefined {
  const withoutPrefix = name.replace(/^mcp_+/, "");
  const canonicalSeparator = withoutPrefix.indexOf("__");
  if (canonicalSeparator > 0) {
    return {
      server: withoutPrefix.slice(0, canonicalSeparator),
      tool: withoutPrefix.slice(canonicalSeparator + 2),
    };
  }

  if (withoutPrefix.endsWith("_exec")) {
    return { server: withoutPrefix.slice(0, -5), tool: "exec" };
  }
  return undefined;
}

function isPostHogExecToolName(name: string): boolean {
  const parts = readPiMcpToolParts(name);
  return (
    !!parts &&
    parts.tool === "exec" &&
    posthogExecServerPattern.test(parts.server)
  );
}

export function parsePiMcpCallDetails(
  name: string,
  args: unknown,
): PiMcpCallDetails | undefined {
  if (name === "mcp") {
    const parsed = piMcpProxyInputSchema.safeParse(args);
    if (!parsed.success) return undefined;
    if (parsed.data.search) {
      return { kind: "search", query: parsed.data.search };
    }
    if (parsed.data.tool) {
      return {
        kind: "tool",
        name: parsed.data.tool,
        ...(parsed.data.args ? { args: parsed.data.args } : {}),
      };
    }
    return undefined;
  }

  if (!isPostHogExecToolName(name)) return undefined;
  const parsed = z
    .object({ command: z.string() })
    .passthrough()
    .safeParse(args);
  if (!parsed.success) return undefined;

  return {
    kind: "tool",
    name,
    args: JSON.stringify(parsed.data),
  };
}

export function readPiMcpCallDetails(
  details: unknown,
): PiMcpCallDetails | undefined {
  const parsed = piMcpCallDetailsSchema.safeParse(details);
  return parsed.success ? parsed.data : undefined;
}

function formatMcpPart(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/([a-z\d])([A-Z])/g, "$1 $2");
}

function pluralizeMcpPart(value: string): string {
  if (value.endsWith("y")) return `${value.slice(0, -1)}ies`;
  if (value.endsWith("s")) return value;
  return `${value}s`;
}

export function formatMcpToolLabel(value: string): string {
  const parts = value.split(/[_-]+/).filter(Boolean);
  if (parts.length === 0) return value;

  const verbs = new Set([
    "check",
    "create",
    "delete",
    "get",
    "inspect",
    "list",
    "query",
    "read",
    "remove",
    "run",
    "search",
    "send",
    "update",
  ]);
  const hasAllSuffix = parts.at(-1) === "all";
  let verbIndex = -1;
  if (hasAllSuffix && verbs.has(parts.at(-2) ?? "")) {
    verbIndex = parts.length - 2;
  } else if (verbs.has(parts.at(-1) ?? "")) {
    verbIndex = parts.length - 1;
  } else if (verbs.has(parts[0] ?? "")) {
    verbIndex = 0;
  }

  if (verbIndex >= 0) {
    const verb = parts[verbIndex];
    const resource = parts.slice(0, verbIndex);
    if (verb && resource.length > 0) {
      const resourceLabel = formatMcpPart(resource.join(" "));
      return `${verb.charAt(0).toUpperCase()}${verb.slice(1)} ${hasAllSuffix ? pluralizeMcpPart(resourceLabel) : resourceLabel}`;
    }
  }

  const label = formatMcpPart(value);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export function formatPiMcpToolName(name: string, toolLabel?: string): string {
  const withoutPrefix = name.replace(/^mcp_+/, "");
  const separator = withoutPrefix.indexOf("__");
  if (separator > 0) {
    const server = withoutPrefix.slice(0, separator);
    const tool = withoutPrefix.slice(separator + 2);
    return `${formatMcpPart(server)} - ${toolLabel ?? formatMcpToolLabel(tool)}`;
  }

  const [server, ...toolParts] = withoutPrefix.split("_");
  if (server && toolParts.length > 0) {
    return `${formatMcpPart(server)} - ${toolLabel ?? formatMcpToolLabel(toolParts.join("_"))}`;
  }
  return formatMcpToolLabel(withoutPrefix);
}

export const piToolCallRecordSchema = z.object({
  id: z.string(),
  name: z.string(),
  title: z.string(),
  kind: z.enum([
    "read",
    "list",
    "edit",
    "delete",
    "move",
    "search",
    "execute",
    "think",
    "fetch",
    "switch_mode",
    "question",
    "other",
  ]),
  status: z.enum(["pending", "in_progress", "completed", "failed"]),
  rawInput: z.unknown(),
  details: piMcpCallDetailsSchema.optional(),
  locations: z
    .array(
      z.object({
        path: z.string(),
        line: z.number().nullable().optional(),
      }),
    )
    .optional(),
});
export type PiToolCallRecord = z.infer<typeof piToolCallRecordSchema>;

export function isPiToolName(name: string): name is PiToolName {
  return name in PI_TOOL_KIND_BY_NAME;
}

function readLocations(
  name: string,
  args: unknown,
): AgentToolCallLocation[] | undefined {
  if (
    (name !== "read" && name !== "ls") ||
    !args ||
    typeof args !== "object" ||
    !("path" in args) ||
    typeof args.path !== "string"
  ) {
    return undefined;
  }

  return [{ path: args.path }];
}

export function createPiToolCallRecord(
  input: PiToolCallInput,
  status: AgentToolCallStatus,
): PiToolCallRecord {
  const locations = readLocations(input.name, input.arguments);
  const details = parsePiMcpCallDetails(input.name, input.arguments);

  return {
    id: input.id,
    name: input.name,
    title: input.name,
    kind: isPiToolName(input.name) ? PI_TOOL_KIND_BY_NAME[input.name] : "other",
    status,
    rawInput: input.arguments,
    ...(details ? { details } : {}),
    ...(locations ? { locations } : {}),
  };
}
