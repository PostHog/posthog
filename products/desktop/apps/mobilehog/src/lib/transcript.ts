import type { StoredLogEntry } from "@posthog/shared";
import { isIdleResumeTurnComplete } from "@posthog/shared";

export type ToolStatus = "pending" | "running" | "completed" | "failed";

export interface PlanEntry {
  content: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  priority?: string;
}

export type Block =
  | { kind: "user"; id: string; text: string }
  | { kind: "agent"; id: string; text: string; complete: boolean }
  | { kind: "thought"; id: string; text: string; at: number }
  | {
      kind: "tool";
      id: string;
      title: string;
      toolName?: string;
      status: ToolStatus;
      input?: Record<string, unknown>;
      output?: unknown;
      parentId?: string;
      // Epoch ms of the first and latest log entries for this call.
      at: number;
      updatedAt: number;
    }
  | { kind: "plan"; id: string; entries: PlanEntry[] };

interface SessionUpdate {
  sessionUpdate?: string;
  content?: { type: string; text: string };
  title?: string;
  toolCallId?: string;
  status?: "pending" | "in_progress" | "completed" | "failed" | null;
  rawInput?: Record<string, unknown>;
  rawOutput?: unknown;
  entries?: PlanEntry[];
  _meta?: { claudeCode?: { toolName?: string; parentToolCallId?: string } };
}

export interface PermissionOption {
  kind: string;
  optionId: string;
  name: string;
}

export interface PermissionRequest {
  requestId: string;
  toolCallId: string;
  title: string;
  input?: Record<string, unknown>;
  options: PermissionOption[];
  chosenOptionId?: string;
}

export interface FoldResult {
  blocks: Block[];
  // Signals for turn state, so the store does not re-walk entries.
  turnEnded: boolean;
  turnFailed: boolean;
  awaitingInput: boolean;
  externalUserMessages: number;
  // Permission requests replayed from the log, for reopened tasks.
  permissionRequests: PermissionRequest[];
  resolvedRequestIds: string[];
  errorMessage: string | null;
}

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

function mapToolStatus(status: SessionUpdate["status"]): ToolStatus {
  switch (status) {
    case "in_progress":
      return "running";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    default:
      return "pending";
  }
}

function entryTime(entry: StoredLogEntry): number {
  const parsed = entry.timestamp ? Date.parse(entry.timestamp) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : Date.now();
}

function last(blocks: Block[]): Block | undefined {
  return blocks[blocks.length - 1];
}

export function closeOpenAgent(blocks: Block[]): void {
  const open = last(blocks);
  if (open?.kind === "agent" && !open.complete) {
    blocks[blocks.length - 1] = { ...open, complete: true };
  }
}

// Folds a batch of log entries into the block list. Consecutive agent chunks
// append to the open agent block, so streaming updates in place.
export function foldEntries(
  previous: Block[],
  entries: StoredLogEntry[],
  localEchoes: Set<string>,
): FoldResult {
  const blocks = [...previous];
  const result: FoldResult = {
    blocks,
    turnEnded: false,
    turnFailed: false,
    awaitingInput: false,
    externalUserMessages: 0,
    permissionRequests: [],
    resolvedRequestIds: [],
    errorMessage: null,
  };

  for (const entry of entries) {
    const method = entry.notification?.method;
    if (!method) continue;

    if (method === "_posthog/turn_complete") {
      if (!isIdleResumeTurnComplete(entry)) {
        result.turnEnded = true;
        closeOpenAgent(blocks);
      }
      continue;
    }
    if (method === "_posthog/task_complete") {
      result.turnEnded = true;
      closeOpenAgent(blocks);
      continue;
    }
    if (method === "_posthog/awaiting_user_input") {
      result.turnEnded = true;
      result.awaitingInput = true;
      closeOpenAgent(blocks);
      continue;
    }
    if (method === "_posthog/error") {
      result.turnEnded = true;
      result.turnFailed = true;
      const params = entry.notification?.params as
        | { message?: string; error?: string }
        | undefined;
      result.errorMessage = params?.message ?? params?.error ?? "Agent error";
      continue;
    }
    if (method === "_posthog/permission_request") {
      const params = entry.notification?.params as
        | {
            requestId?: string;
            toolCallId?: string;
            toolCall?: {
              toolCallId?: string;
              title?: string;
              rawInput?: Record<string, unknown>;
            };
            options?: PermissionOption[];
          }
        | undefined;
      const toolCallId = params?.toolCallId ?? params?.toolCall?.toolCallId;
      if (params?.requestId && toolCallId) {
        result.permissionRequests.push({
          requestId: params.requestId,
          toolCallId,
          title: params.toolCall?.title ?? "Permission needed",
          input: params.toolCall?.rawInput,
          options: params.options ?? [],
        });
      }
      continue;
    }
    if (method === "_posthog/permission_resolved") {
      const params = entry.notification?.params as
        | { requestId?: string }
        | undefined;
      if (params?.requestId) result.resolvedRequestIds.push(params.requestId);
      continue;
    }
    if (method !== "session/update") continue;

    const update = (entry.notification?.params as { update?: SessionUpdate })
      ?.update;
    if (!update?.sessionUpdate) continue;

    switch (update.sessionUpdate) {
      case "user_message_chunk": {
        const text = update.content?.text ?? "";
        if (!text) break;
        if (localEchoes.has(text)) {
          localEchoes.delete(text);
          break;
        }
        result.externalUserMessages += 1;
        closeOpenAgent(blocks);
        blocks.push({ kind: "user", id: nextId("user"), text });
        break;
      }
      case "agent_message_chunk": {
        const text = update.content?.text;
        if (!text) break;
        const open = last(blocks);
        if (open?.kind === "agent" && !open.complete) {
          blocks[blocks.length - 1] = { ...open, text: open.text + text };
        } else {
          blocks.push({
            kind: "agent",
            id: nextId("agent"),
            text,
            complete: false,
          });
        }
        break;
      }
      case "agent_message": {
        const text = update.content?.text;
        if (!text) break;
        const open = last(blocks);
        if (open?.kind === "agent" && !open.complete) {
          blocks[blocks.length - 1] = { ...open, text, complete: true };
        } else {
          blocks.push({
            kind: "agent",
            id: nextId("agent"),
            text,
            complete: true,
          });
        }
        break;
      }
      case "agent_thought_chunk": {
        const text = update.content?.text;
        if (!text) break;
        const open = last(blocks);
        if (open?.kind === "thought") {
          blocks[blocks.length - 1] = { ...open, text: open.text + text };
        } else {
          blocks.push({
            kind: "thought",
            id: nextId("thought"),
            text,
            at: entryTime(entry),
          });
        }
        break;
      }
      case "tool_call":
      case "tool_call_update": {
        const toolCallId = update.toolCallId;
        if (!toolCallId) break;
        const meta = update._meta?.claudeCode;
        const index = blocks.findIndex(
          (block) => block.kind === "tool" && block.id === toolCallId,
        );
        const existing =
          index >= 0 ? (blocks[index] as Block & { kind: "tool" }) : null;
        const merged: Block = {
          kind: "tool",
          id: toolCallId,
          title: update.title ?? existing?.title ?? meta?.toolName ?? "Tool",
          toolName: meta?.toolName ?? existing?.toolName,
          status: update.status
            ? mapToolStatus(update.status)
            : (existing?.status ?? "pending"),
          input: update.rawInput ?? existing?.input,
          output:
            update.rawOutput !== undefined
              ? update.rawOutput
              : existing?.output,
          parentId: meta?.parentToolCallId ?? existing?.parentId,
          at: existing?.at ?? entryTime(entry),
          updatedAt: entryTime(entry),
        };
        if (existing) {
          blocks[index] = merged;
        } else {
          // Close any streaming agent text so the next chunk starts a new bubble.
          const open = last(blocks);
          if (open?.kind === "agent" && !open.complete) {
            blocks[blocks.length - 1] = { ...open, complete: true };
          }
          blocks.push(merged);
        }
        break;
      }
      case "plan": {
        if (!Array.isArray(update.entries)) break;
        const index = blocks.findIndex((block) => block.kind === "plan");
        const plan: Block = {
          kind: "plan",
          id: "plan",
          entries: update.entries,
        };
        if (index >= 0) blocks[index] = plan;
        else blocks.push(plan);
        break;
      }
      default:
        break;
    }
  }

  return result;
}
