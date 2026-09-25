import { createAppendOnlyTracker } from "@posthog/core/sessions/appendOnlyTracker";
import {
  type AcpMessage,
  isJsonRpcNotification,
  readMcpToolDescriptor,
} from "@posthog/shared";
import { useMemo, useRef } from "react";

interface ToolCallState {
  toolCallIds: Set<string>;
  completedCallIds: Set<string>;
}

export function createCompletedToolCallTracker(toolName: string) {
  return createAppendOnlyTracker<ToolCallState, number>({
    init: () => ({ toolCallIds: new Set(), completedCallIds: new Set() }),
    processEvent: (state, event) => {
      const msg = event.message;
      if (!isJsonRpcNotification(msg)) return;
      if (msg.method !== "session/update") return;

      const update = (
        msg.params as
          | {
              update?: {
                sessionUpdate?: string;
                toolCallId?: string;
                status?: string;
                _meta?: unknown;
              };
            }
          | undefined
      )?.update;
      if (
        !update?.toolCallId ||
        (update.sessionUpdate !== "tool_call" &&
          update.sessionUpdate !== "tool_call_update")
      ) {
        return;
      }

      if (readMcpToolDescriptor(update._meta)?.tool === toolName) {
        state.toolCallIds.add(update.toolCallId);
      }
      if (
        update.status === "completed" &&
        state.toolCallIds.has(update.toolCallId)
      ) {
        state.completedCallIds.add(update.toolCallId);
      }
    },
    getResult: (state) => state.completedCallIds.size,
  });
}

export function useCompletedToolCalls(
  events: AcpMessage[],
  toolName: string,
): number {
  const trackerRef = useRef<ReturnType<
    typeof createCompletedToolCallTracker
  > | null>(null);
  trackerRef.current ??= createCompletedToolCallTracker(toolName);
  const tracker = trackerRef.current;
  return useMemo(() => tracker.update(events), [events, tracker]);
}
