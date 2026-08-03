import { create } from "zustand";

// Thread retention: a thread is tiny (a runtime-error flag + a browse pointer),
// but threads for every canvas ever visited would otherwise stay resident for
// the app's lifetime. Keep the most recently used few; at worst an evicted
// thread loses an in-progress version *browse* position.
const MAX_THREADS = 8;

// Per-canvas VIEW state for a freeform canvas. Source code, version history,
// and the author context are server-versioned (dashboards.get / source /
// versions) and the rendered output is the published build's artifact — none of
// that lives here. This store owns only what the client browses or observes
// locally: the sandbox's runtime-error signal, and which historical version (if
// any) the user is browsing.
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
  /** MRU access order for eviction, oldest first. Store state (not a module
   * closure) so devtools/tests see it and HMR can't desync it from `threads`. */
  threadOrder: string[];
  /** Threads with a live view. Eviction skips these even past the cap, so an
   * open canvas can never lose its browse/runtimeError to a patch burst. */
  mountedThreadIds: string[];

  /** Browse a historical source version (null = back to the head). */
  setBrowseVersion: (threadId: string, versionId: string | null) => void;
  setRuntimeError: (threadId: string, message: string | null) => void;
  /** Register/unregister a mounted canvas view against its thread. */
  setThreadMounted: (threadId: string, mounted: boolean) => void;
}

/** The dashboardId a thread is keyed on ("dashboard:<id>" → "<id>"). */
export function dashboardIdOf(threadId: string): string {
  return threadId.replace(/^dashboard:/, "");
}

export const useFreeformChatStore = create<FreeformChatStore>()((set) => {
  // Every patch refreshes the thread's recency and evicts the least recently
  // used threads beyond the cap. The thread just patched is always the most
  // recent, so it can never evict itself; mounted threads are never evicted at
  // all, so a burst of patches to background threads can't blow away a view the
  // user has open.
  const patch = (
    threadId: string,
    fn: (prev: FreeformThreadState) => FreeformThreadState,
  ) => {
    set((s) => {
      const threadOrder = [
        ...s.threadOrder.filter((id) => id !== threadId),
        threadId,
      ];
      const threads = {
        ...s.threads,
        [threadId]: fn(s.threads[threadId] ?? EMPTY_FREEFORM_THREAD),
      };
      const mounted = new Set(s.mountedThreadIds);
      let evictable = threadOrder.filter((id) => !mounted.has(id)).length;
      let index = 0;
      while (evictable > MAX_THREADS && index < threadOrder.length) {
        const candidate = threadOrder[index];
        if (mounted.has(candidate)) {
          index++;
          continue;
        }
        threadOrder.splice(index, 1);
        delete threads[candidate];
        evictable--;
      }
      return { threads, threadOrder };
    });
  };

  return {
    threads: {},
    threadOrder: [],
    mountedThreadIds: [],

    setBrowseVersion: (threadId, versionId) => {
      patch(threadId, (prev) => ({ ...prev, browseVersionId: versionId }));
    },

    setRuntimeError: (threadId, message) => {
      patch(threadId, (prev) => ({ ...prev, runtimeError: message }));
    },

    setThreadMounted: (threadId, mounted) => {
      set((s) => ({
        mountedThreadIds: mounted
          ? s.mountedThreadIds.includes(threadId)
            ? s.mountedThreadIds
            : [...s.mountedThreadIds, threadId]
          : s.mountedThreadIds.filter((id) => id !== threadId),
      }));
    },
  };
});

export function useFreeformThread(threadId: string): FreeformThreadState {
  return useFreeformChatStore(
    (s) => s.threads[threadId] ?? EMPTY_FREEFORM_THREAD,
  );
}
