import { type AcpMessage, opIdForToolCall } from "@posthog/shared";
import { buildCloudEventSummary } from "../task-detail/cloudToolChanges";
import type { SketchpadSyncClient } from "./sketchpadSync";
import { sketchpadToolName, toolCallToOp } from "./toolCalls";

export function applySketchpadToolCalls(
  events: readonly AcpMessage[],
  client: SketchpadSyncClient,
  taskId: string,
  onFragmentAdded?: (id: string) => void,
): void {
  for (const record of buildCloudEventSummary([...events]).toolCalls.values()) {
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
