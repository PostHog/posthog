import { type AcpMessage, opIdForToolCall } from "@posthog/shared";
import type { SketchpadSyncClient } from "./sketchpadSync";
import { sketchpadToolName, toolCallToOp } from "./toolCalls";

interface PartialRecord {
  toolCallId: string;
  meta?: unknown;
  rawInput?: unknown;
  status?: string;
}

export function applySketchpadToolCalls(
  events: readonly AcpMessage[],
  client: SketchpadSyncClient,
  taskId: string,
  onFragmentAdded?: (id: string) => void,
): void {
  const byId = new Map<string, PartialRecord>();

  for (const event of events) {
    const update = readSessionUpdate(event);
    if (!update) continue;
    const existing = byId.get(update.toolCallId);
    byId.set(update.toolCallId, {
      toolCallId: update.toolCallId,
      meta: update.meta ?? existing?.meta,
      rawInput: update.rawInput ?? existing?.rawInput,
      status: update.status ?? existing?.status,
    });
  }

  for (const record of byId.values()) {
    if (record.status !== "completed") continue;
    const opId = opIdForToolCall(record.toolCallId, 0);
    if (client.hasOp(opId)) continue;
    const tool = sketchpadToolName(record.meta);
    if (!tool) continue;
    const op = toolCallToOp(tool, record.rawInput, client.getState().snapshot);
    if (!op) continue;
    client.applyLocal([op], { kind: "agent", taskId }, [opId]);
    if (op.type === "add_fragment") onFragmentAdded?.(op.fragment.id);
  }
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
