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
  return {
    id: input.id,
    name: input.name,
    title: input.name,
    kind: isPiToolName(input.name) ? PI_TOOL_KIND_BY_NAME[input.name] : "other",
    status,
    rawInput: input.arguments,
    ...(locations ? { locations } : {}),
  };
}
