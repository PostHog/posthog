import { logger } from "@posthog/ui/shell/logger";
import { create } from "zustand";
import { hostClient } from "../hostClient";

const log = logger.scope("freeform-edit-store");

// Thread retention: a thread is tiny now (a context buffer + a few flags), but
// threads for every canvas ever visited would otherwise stay resident for the
// app's lifetime. Keep the most recently used few; an evicted thread reseeds
// its context from the saved record on the next visit, so at worst an
// in-progress version *browse* position is lost.
const MAX_THREADS = 8;

// Per-canvas VIEW state for a freeform canvas. Source code and version history
// are server-versioned now (dashboards.source / dashboards.versions) and the
// rendered output is the published build's artifact — none of that lives here.
// This store owns only what the client edits or browses locally: the author
// context buffer (with its saveContext autosave), the sandbox's runtime-error
// signal, and which historical version (if any) the user is browsing.
export interface FreeformThreadState {
  /** Live context editing buffer (markdown passed to generation tasks). */
  context: string;
  /** True once the user has edited the buffer. A touched buffer is
   * authoritative and is never overwritten by a record seed — a stale record
   * poll landing mid-edit must not clobber unsaved typing. */
  contextTouched: boolean;
  /** True while a saveContext mutation is in flight (toolbar saving spinner). */
  isSavingContext: boolean;
  /** Latest runtime/compile error reported by the sandbox (self-repair signal). */
  runtimeError: string | null;
  /** Historical source version being browsed (edit mode); null = the head. */
  browseVersionId: string | null;
}

export const EMPTY_FREEFORM_THREAD: FreeformThreadState = {
  context: "",
  contextTouched: false,
  isSavingContext: false,
  runtimeError: null,
  browseVersionId: null,
};

interface FreeformChatStore {
  threads: Record<string, FreeformThreadState>;
  /** MRU access order for eviction, oldest first. Store state (not a module
   * closure) so devtools/tests see it and HMR can't desync it from `threads`. */
  threadOrder: string[];

  /** Seed the context buffer from the saved record — only while the buffer is
   * untouched, so a record refetch can't clobber the user's typing. */
  seedContext: (threadId: string, context: string) => void;
  /** Live-update the context text as the user types (no save yet). */
  setContext: (threadId: string, context: string) => void;
  /** Commit a context edit (on blur / debounce): persist the buffer via the
   * host saveContext mutation. No-ops while the buffer is untouched. */
  commitContext: (threadId: string) => void;
  /** Browse a historical source version (null = back to the head). */
  setBrowseVersion: (threadId: string, versionId: string | null) => void;
  setRuntimeError: (threadId: string, message: string | null) => void;
}

// The dashboardId a thread persists to ("dashboard:<id>" → "<id>").
function dashboardIdOf(threadId: string): string {
  return threadId.replace(/^dashboard:/, "");
}

export const useFreeformChatStore = create<FreeformChatStore>()((set, get) => {
  // Every patch refreshes a thread's recency; eviction runs only from the
  // mount-time seeding path (seedContext) so an edit mid-session never drops
  // another thread out from under a mounted view racing a save.
  const touch = (threadId: string) => {
    set((s) => ({
      threadOrder: [...s.threadOrder.filter((id) => id !== threadId), threadId],
    }));
  };

  const evictExcessThreads = () => {
    // Walk oldest-first, skipping (not aborting on) threads with a save in
    // flight — an abort would let one slow save at the front block the cap for
    // every thread behind it.
    let excess = get().threadOrder.length - MAX_THREADS;
    for (const oldest of [...get().threadOrder]) {
      if (excess <= 0) break;
      if (get().threads[oldest]?.isSavingContext) continue;
      excess--;
      set((s) => {
        const { [oldest]: _evicted, ...rest } = s.threads;
        return {
          threads: rest,
          threadOrder: s.threadOrder.filter((id) => id !== oldest),
        };
      });
    }
  };

  const patch = (
    threadId: string,
    fn: (prev: FreeformThreadState) => FreeformThreadState,
  ) => {
    touch(threadId);
    set((s) => ({
      threads: {
        ...s.threads,
        [threadId]: fn(s.threads[threadId] ?? EMPTY_FREEFORM_THREAD),
      },
    }));
  };

  return {
    threads: {},
    threadOrder: [],

    seedContext: (threadId, context) => {
      touch(threadId);
      evictExcessThreads();
      const cur = get().threads[threadId];
      if (cur?.contextTouched || cur?.context === context) return;
      patch(threadId, (prev) => ({ ...prev, context }));
    },

    setContext: (threadId, context) => {
      patch(threadId, (prev) => ({ ...prev, context, contextTouched: true }));
    },

    commitContext: (threadId) => {
      const t = get().threads[threadId];
      // Untouched buffer = nothing beyond the seeded record value to save.
      if (!t?.contextTouched) return;
      patch(threadId, (prev) => ({ ...prev, isSavingContext: true }));
      // Persist to the server-side record; never throws (an autosave failure
      // is logged, and the buffer stays authoritative for the next commit).
      void (async () => {
        try {
          await hostClient().dashboards.saveContext.mutate({
            id: dashboardIdOf(threadId),
            context: t.context,
          });
        } catch (error) {
          log.error("Canvas context autosave failed", { error });
        } finally {
          patch(threadId, (prev) => ({ ...prev, isSavingContext: false }));
        }
      })();
    },

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
