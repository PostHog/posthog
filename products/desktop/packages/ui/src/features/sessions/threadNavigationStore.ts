import { useEffect } from "react";
import { create } from "zustand";

interface ThreadNavigationStoreState {
  /** taskId → conversation item id the transcript should scroll to, if any. */
  scrollRequests: Record<string, string | null>;
  /** taskId → how many transcripts are mounted and listening. A request with no listener
   *  goes nowhere, so callers offer the jump only when this is non-zero. */
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
 * Lets a pane outside the transcript ask it to scroll to a message, because the Activity
 * timeline sits in a sibling tree and can't reach the scroller's context or the windowed
 * body's jump callback directly. Mirrors `reviewNavigationStore`'s scroll-request shape.
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

/** The target row may not be registered yet, and the tab holding the transcript may only
 *  just have been activated, so the first frame after a request is routinely too early. */
const JUMP_ATTEMPT_FRAMES = 60;

/** Rows above the target measure late (diffs, highlighted code, images), which moves it out
 *  from under an offset already committed, so a landed jump is re-issued for a few frames. */
const JUMP_SETTLE_FRAMES = 3;

/**
 * Hands a pending request to the transcript's own jump. Each transcript jumps differently
 * (DOM registry, virtualizer index), so the store carries only the target.
 *
 * The request survives a jump that did not land and is retried until one does, so a
 * transcript mounting after the request still answers it. That is what makes the jump work
 * from a tab that was not on screen when the reader asked.
 */
export function useThreadScrollRequest(
  taskId: string | undefined,
  jumpToMessage: (messageId: string) => boolean,
): void {
  const requestedMessageId = useThreadNavigationStore((state) =>
    taskId ? state.scrollRequests[taskId] : null,
  );

  // So a pane offering the jump can hide the affordance when nothing is listening.
  useEffect(() => {
    if (!taskId) return;
    const { registerTranscript, unregisterTranscript } =
      useThreadNavigationStore.getState();
    registerTranscript(taskId);
    return () => unregisterTranscript(taskId);
  }, [taskId]);

  useEffect(() => {
    if (!taskId || !requestedMessageId) return;
    let frame: number | null = null;
    let attempts = 0;
    let settles = 0;
    const step = () => {
      frame = null;
      const landed = jumpToMessage(requestedMessageId);
      if (
        landed
          ? ++settles > JUMP_SETTLE_FRAMES
          : ++attempts > JUMP_ATTEMPT_FRAMES
      ) {
        // Giving up clears too: a target the transcript never renders must not leave a
        // request pending forever. Read via getState so the action isn't an effect dependency.
        useThreadNavigationStore.getState().clearScrollRequest(taskId);
        return;
      }
      frame = requestAnimationFrame(step);
    };
    step();
    return () => {
      if (frame !== null) cancelAnimationFrame(frame);
    };
  }, [taskId, requestedMessageId, jumpToMessage]);
}

export function useHasTranscriptListener(taskId: string | undefined): boolean {
  return useThreadNavigationStore((state) =>
    taskId ? (state.listeners[taskId] ?? 0) > 0 : false,
  );
}
