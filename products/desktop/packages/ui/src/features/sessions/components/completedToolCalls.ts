import { createAppendOnlyTracker } from "@posthog/core/sessions/appendOnlyTracker";
import { readToolCallUpdate } from "@posthog/core/sessions/toolCallUpdates";
import type { AcpMessage } from "@posthog/shared";
import { useMemo, useRef } from "react";

interface ToolCallState {
  toolCallIds: Set<string>;
  completedCallIds: Set<string>;
}

export function createCompletedToolCallTracker(toolName: string) {
  return createAppendOnlyTracker<ToolCallState, number>({
    init: () => ({ toolCallIds: new Set(), completedCallIds: new Set() }),
    processEvent: (state, event) => {
      const update = readToolCallUpdate(event);
      if (!update) return;
      if (update.tool === toolName) state.toolCallIds.add(update.toolCallId);
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
