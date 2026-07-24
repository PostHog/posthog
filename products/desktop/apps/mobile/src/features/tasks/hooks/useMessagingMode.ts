import { useCallback } from "react";
import { useMessageQueueStore } from "../stores/messageQueueStore";
import {
  type MessagingMode,
  useMessagingModeStore,
} from "../stores/messagingModeStore";
import { useTaskSessionStore } from "../stores/taskSessionStore";

/** Effective mode for a task: per-task override, else the global default. */
export function useMessagingMode(taskId: string | undefined): MessagingMode {
  return useMessagingModeStore((s) => s.getEffectiveMode(taskId));
}

export function useQueuedCount(taskId: string | undefined): number {
  return useMessageQueueStore((s) => (taskId ? s.getQueue(taskId).length : 0));
}

/**
 * Toggle the per-task messaging mode. Switching to Steer flushes any buffered
 * messages into the current turn so nothing stays stuck in a queue the user
 * just turned off.
 */
export function useToggleMessagingMode(taskId: string | undefined): () => void {
  const mode = useMessagingMode(taskId);
  return useCallback(() => {
    if (!taskId) return;
    const next: MessagingMode = mode === "steer" ? "queue" : "steer";
    useMessagingModeStore.getState().setMode(taskId, next);
    if (next === "steer") {
      void useTaskSessionStore.getState().flushQueuedMessages(taskId);
    }
  }, [taskId, mode]);
}
