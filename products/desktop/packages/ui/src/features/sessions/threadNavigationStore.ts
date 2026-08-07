import { useEffect } from "react";
import { create } from "zustand";

interface ThreadNavigationStoreState {
  /** taskId → conversation item id the transcript should scroll to, if any. */
  scrollRequests: Record<string, string | null>;
}

interface ThreadNavigationStoreActions {
  requestScrollToMessage: (taskId: string, messageId: string) => void;
  clearScrollRequest: (taskId: string) => void;
}

type ThreadNavigationStore = ThreadNavigationStoreState &
  ThreadNavigationStoreActions;

/**
 * Lets a pane outside the transcript ask it to scroll to a message — the
 * Activity timeline sits in a sibling tree, so it can't reach the scroller's
 * context or the windowed body's jump callback directly. Mirrors
 * `reviewNavigationStore`'s scroll-request shape: the writer sets a request, the
 * transcript consumes it and clears it.
 */
export const useThreadNavigationStore = create<ThreadNavigationStore>()(
  (set) => ({
    scrollRequests: {},

    requestScrollToMessage: (taskId, messageId) =>
      set((state) => ({
        scrollRequests: { ...state.scrollRequests, [taskId]: messageId },
      })),

    clearScrollRequest: (taskId) =>
      set((state) => ({
        scrollRequests: { ...state.scrollRequests, [taskId]: null },
      })),
  }),
);

/**
 * Consumes a pending request for this task, handing it to the transcript's own
 * jump and clearing it. Each transcript jumps differently (DOM registry,
 * virtualizer index, grouped-row index), so the store carries only the target.
 */
export function useThreadScrollRequest(
  taskId: string | undefined,
  jumpToMessage: (messageId: string) => void,
): void {
  const requestedMessageId = useThreadNavigationStore((state) =>
    taskId ? state.scrollRequests[taskId] : null,
  );

  useEffect(() => {
    if (!taskId || !requestedMessageId) return;
    jumpToMessage(requestedMessageId);
    // Clear via getState so the action isn't an effect dependency.
    useThreadNavigationStore.getState().clearScrollRequest(taskId);
  }, [taskId, requestedMessageId, jumpToMessage]);
}
