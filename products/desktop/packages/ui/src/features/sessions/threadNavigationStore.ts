import { useEffect } from "react";
import { create } from "zustand";

interface ThreadNavigationStoreState {
  /** taskId → conversation item id the transcript should scroll to, if any. */
  scrollRequests: Record<string, string | null>;
  /** taskId → how many transcripts are mounted and listening. A request with no
   *  listener goes nowhere, so callers offer the jump only when this is non-zero. */
  listeners: Record<string, number>;
}

interface ThreadNavigationStoreActions {
  requestScrollToMessage: (taskId: string, messageId: string) => void;
  clearScrollRequest: (taskId: string) => void;
  registerTranscript: (taskId: string) => void;
  unregisterTranscript: (taskId: string) => void;
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
    listeners: {},

    requestScrollToMessage: (taskId, messageId) =>
      set((state) => ({
        scrollRequests: { ...state.scrollRequests, [taskId]: messageId },
      })),

    clearScrollRequest: (taskId) =>
      set((state) => ({
        scrollRequests: { ...state.scrollRequests, [taskId]: null },
      })),

    registerTranscript: (taskId) =>
      set((state) => ({
        listeners: {
          ...state.listeners,
          [taskId]: (state.listeners[taskId] ?? 0) + 1,
        },
      })),

    unregisterTranscript: (taskId) =>
      set((state) => {
        const next = (state.listeners[taskId] ?? 0) - 1;
        const listeners = { ...state.listeners };
        if (next > 0) listeners[taskId] = next;
        else delete listeners[taskId];
        return { listeners };
      }),
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

  // Announce that this transcript can answer a jump, so a pane that offers one can hide
  // the affordance when nothing is listening, because a dead button is worse than none.
  useEffect(() => {
    if (!taskId) return;
    const { registerTranscript, unregisterTranscript } =
      useThreadNavigationStore.getState();
    registerTranscript(taskId);
    return () => unregisterTranscript(taskId);
  }, [taskId]);

  useEffect(() => {
    if (!taskId || !requestedMessageId) return;
    jumpToMessage(requestedMessageId);
    // Clear via getState so the action isn't an effect dependency.
    useThreadNavigationStore.getState().clearScrollRequest(taskId);
  }, [taskId, requestedMessageId, jumpToMessage]);
}

/** Whether a transcript for this task is mounted to answer a scroll request. */
export function useHasTranscriptListener(taskId: string | undefined): boolean {
  return useThreadNavigationStore((state) =>
    taskId ? (state.listeners[taskId] ?? 0) > 0 : false,
  );
}
