import type { BoardSyncClient } from "@posthog/core/canvas-v2/boardSync";
import { collectCanvasV2ToolCalls } from "@posthog/core/canvas-v2/toolCallEvents";
import { toolCallToOps } from "@posthog/core/canvas-v2/toolCalls";
import { opIdForToolCall } from "@posthog/shared";
import { useSessionSelector } from "@posthog/ui/features/sessions/useSession";
import { useEffect } from "react";

/**
 * Turns the board agent's completed tool calls into board operations. The
 * operation id comes from the tool call id, so two people who watch the same
 * session cannot apply one change twice.
 */
export function useApplyBoardToolCalls(
  client: BoardSyncClient | null,
  taskId: string | undefined,
  onFragmentAdded?: (id: string) => void,
): void {
  const events = useSessionSelector(taskId, (session) => session?.events);

  useEffect(() => {
    if (!client || !taskId || !events) return;
    for (const call of collectCanvasV2ToolCalls(events)) {
      const ops = toolCallToOps(
        call.tool,
        call.rawInput,
        client.getState().snapshot,
      );
      if (ops.length === 0) continue;
      const opIds = ops.map((_, index) =>
        opIdForToolCall(call.toolCallId, index),
      );
      if (opIds.every((opId) => client.hasOp(opId))) continue;
      client.applyLocal(ops, { kind: "agent", taskId }, opIds);
      const added = ops.find((op) => op.type === "add_fragment");
      if (added?.type === "add_fragment") onFragmentAdded?.(added.fragment.id);
    }
  }, [client, taskId, events, onFragmentAdded]);
}
