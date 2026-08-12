import { create } from "zustand";

// Per-canvas VIEW state for a freeform canvas. Source code, version history,
// and the author context are server-versioned (dashboards.get / source /
// versions) and the rendered output is the published build's artifact — none of
// that lives here. This store owns only what the client browses or observes
// locally: the sandbox's runtime-error signal, and which historical version (if
// any) the user is browsing. Threads are tiny (two nullable strings), so they
// simply accumulate for the app's lifetime — no eviction.
export interface FreeformThreadState {
  /** Latest runtime/compile error reported by the sandbox (self-repair signal). */
  runtimeError: string | null;
  /** Historical source version being browsed (edit mode); null = the head. */
  browseVersionId: string | null;
}

export const EMPTY_FREEFORM_THREAD: FreeformThreadState = {
  runtimeError: null,
  browseVersionId: null,
};

interface FreeformChatStore {
  threads: Record<string, FreeformThreadState>;

  /** Browse a historical source version (null = back to the head). */
  setBrowseVersion: (threadId: string, versionId: string | null) => void;
  setRuntimeError: (threadId: string, message: string | null) => void;
}

/** The dashboardId a thread is keyed on ("dashboard:<id>" → "<id>"). */
export function dashboardIdOf(threadId: string): string {
  return threadId.replace(/^dashboard:/, "");
}

export const useFreeformChatStore = create<FreeformChatStore>()((set) => {
  const patch = (
    threadId: string,
    fn: (prev: FreeformThreadState) => FreeformThreadState,
  ) => {
    set((s) => ({
      threads: {
        ...s.threads,
        [threadId]: fn(s.threads[threadId] ?? EMPTY_FREEFORM_THREAD),
      },
    }));
  };

  return {
    threads: {},

    setBrowseVersion: (threadId, versionId) => {
      patch(threadId, (prev) => ({ ...prev, browseVersionId: versionId }));
    },

    setRuntimeError: (threadId, message) => {
      patch(threadId, (prev) => ({ ...prev, runtimeError: message }));
    },
  };
});

export function useFreeformThread(threadId: string): FreeformThreadState {
  return useFreeformChatStore(
    (s) => s.threads[threadId] ?? EMPTY_FREEFORM_THREAD,
  );
}
