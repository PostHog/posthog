import type { AcpMessage } from "@posthog/shared";
import { canvasV2ToolName, isCanvasV2ToolCall } from "./toolCalls";

export interface CanvasV2ToolCallRecord {
  toolCallId: string;
  tool: string;
  rawInput: unknown;
  status: string;
}

interface PartialRecord {
  toolCallId: string;
  meta?: unknown;
  rawInput?: unknown;
  status?: string;
}

/**
 * Completed canvas tool calls of one session, in the order the agent made them.
 * Reads the raw event log, because a tool call and its later status update
 * arrive as two separate notifications.
 */
export function collectCanvasV2ToolCalls(
  events: readonly AcpMessage[],
): CanvasV2ToolCallRecord[] {
  const byId = new Map<string, PartialRecord>();
  const order: string[] = [];

  for (const event of events) {
    const update = readSessionUpdate(event);
    if (!update) continue;
    const existing = byId.get(update.toolCallId);
    if (!existing) {
      order.push(update.toolCallId);
      byId.set(update.toolCallId, update);
      continue;
    }
    byId.set(update.toolCallId, {
      toolCallId: update.toolCallId,
      meta: update.meta ?? existing.meta,
      rawInput: update.rawInput ?? existing.rawInput,
      status: update.status ?? existing.status,
    });
  }

  const records: CanvasV2ToolCallRecord[] = [];
  for (const id of order) {
    const record = byId.get(id);
    if (!record || record.status !== "completed") continue;
    if (!isCanvasV2ToolCall(record.meta)) continue;
    const tool = canvasV2ToolName(record.meta);
    if (!tool) continue;
    records.push({
      toolCallId: id,
      tool,
      rawInput: record.rawInput,
      status: record.status,
    });
  }
  return records;
}

function readSessionUpdate(event: AcpMessage): PartialRecord | null {
  const message = asRecord(event.message);
  if (!message || message.method !== "session/update") return null;
  const params = asRecord(message.params);
  const update = asRecord(params?.update);
  if (!update) return null;
  const kind = update.sessionUpdate;
  if (kind !== "tool_call" && kind !== "tool_call_update") return null;
  const toolCallId = update.toolCallId;
  if (typeof toolCallId !== "string" || toolCallId.length === 0) return null;
  return {
    toolCallId,
    meta: update._meta,
    rawInput: update.rawInput,
    status: typeof update.status === "string" ? update.status : undefined,
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}
