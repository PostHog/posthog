import type { FreeformVersion } from "@posthog/core/canvas/freeformSchemas";
import { logger } from "@posthog/ui/shell/logger";
import { create } from "zustand";
import { hostClient } from "../hostClient";

const log = logger.scope("freeform-edit-store");

// Edit-history retention: each version keeps a full copy of the canvas source
// plus context, so unbounded history grows by whole-document copies. Oldest
// versions fall off past this cap.
const MAX_VERSIONS = 50;

// Thread retention: each thread holds up to MAX_VERSIONS whole-document copies,
// and threads for every canvas ever visited would otherwise stay resident for
// the app's lifetime (browser tabs make visiting many canvases cheap). Keep the
// most recently used few; an evicted thread reseeds from the saved record on
// the next visit — the working copy autosaves on every committed edit, so only
// an in-progress version *browse* position is lost.
const MAX_THREADS = 8;

// Working copy of a freeform canvas's source + edit history. Generation no
// longer streams in-process — it runs as a dedicated task that publishes the
// result into the canvas's saved record (see useGenerateFreeformCanvas). This
// store now owns only the EDIT concerns: seeding from the saved record, version
// browsing (undo/redo/revert), the author context, runtime-error tracking, and
// autosave of manual changes.
export interface FreeformThreadState {
  /** The currently-rendered source. */
  code: string;
  /** Ordered edit history (oldest first). */
  versions: FreeformVersion[];
  /** Which version is live (undo/redo moves this). */
  currentVersionId: string | null;
  /** The canvas's template id, so a generation task gets the matching prompt. */
  templateId: string | null;
  /** Author-written context (markdown), passed to a generation task. */
  context: string;
  /** True while an autosave is in flight (drives the toolbar's saving spinner). */
  isSaving: boolean;
  /** Latest runtime/compile error reported by the sandbox (self-repair signal). */
  runtimeError: string | null;
}

export const EMPTY_FREEFORM_THREAD: FreeformThreadState = {
  code: "",
  versions: [],
  currentVersionId: null,
  templateId: null,
  context: "",
  isSaving: false,
  runtimeError: null,
};

interface FreeformChatStore {
  threads: Record<string, FreeformThreadState>;
  /** MRU access order for eviction, oldest first. Store state (not a module
   * closure) so devtools/tests see it and HMR can't desync it from `threads`. */
  threadOrder: string[];

  /** Seed a thread from a saved record (only if the thread is still empty).
   * The templateId is recorded regardless so a generation gets the right prompt. */
  ensureCode: (threadId: string, record: SavedFreeform) => void;
  /** Reconcile a thread with the latest saved record: adopt a newly-published
   * version (e.g. produced by a generation task) over the local working copy. */
  syncFromRecord: (threadId: string, record: SavedFreeform) => void;
  /** Live-update the context text as the user types (no version/save yet). */
  setContext: (threadId: string, context: string) => void;
  /** Commit a context edit (on blur / debounce): if it changed, snapshot a new
   * version (coalescing consecutive context-only edits) and autosave. */
  commitContext: (threadId: string) => void;
  undo: (threadId: string) => void;
  redo: (threadId: string) => void;
  setRuntimeError: (threadId: string, message: string | null) => void;
  /**
   * Revert: when viewing a non-latest version, make it the head (drop the newer
   * versions) and autosave. The canvas then continues from this version.
   */
  revert: (threadId: string) => void;
  /** Cancel a version browse: jump back to the latest version (no save). */
  goToLatest: (threadId: string) => void;
}

// The saved-record shape used to seed / revert a thread.
interface SavedFreeform {
  code?: string;
  versions?: FreeformVersion[];
  currentVersionId?: string;
  /** The canvas's template id (drives which React-tier prompt a task uses). */
  templateId?: string;
  /** Author-written context (markdown) passed to a generation task. */
  context?: string;
}

function newId(): string {
  return crypto.randomUUID();
}

// The dashboardId a thread persists to ("dashboard:<id>" → "<id>").
function dashboardIdOf(threadId: string): string {
  return threadId.replace(/^dashboard:/, "");
}

export const useFreeformChatStore = create<FreeformChatStore>()((set, get) => {
  // Every patch refreshes a thread's recency; eviction runs only from the
  // mount-time seeding paths (ensureCode / syncFromRecord) so an edit
  // mid-session never drops another thread out from under a mounted view
  // racing a save.
  const touch = (threadId: string) => {
    set((s) => ({
      threadOrder: [...s.threadOrder.filter((id) => id !== threadId), threadId],
    }));
  };

  const evictExcessThreads = () => {
    // Walk oldest-first, skipping (not aborting on) threads with a save in
    // flight — an abort would let one slow autosave at the front block the
    // cap for every thread behind it.
    let excess = get().threadOrder.length - MAX_THREADS;
    for (const oldest of [...get().threadOrder]) {
      if (excess <= 0) break;
      if (get().threads[oldest]?.isSaving) continue;
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

  // Autosave the current code + history to the backend, toggling isSaving so the
  // toolbar can show a spinner. Never throws.
  const persist = async (threadId: string) => {
    const t = get().threads[threadId];
    if (!t) return;
    patch(threadId, (prev) => ({ ...prev, isSaving: true }));
    try {
      await hostClient().dashboards.saveFreeform.mutate({
        id: dashboardIdOf(threadId),
        code: t.code,
        versions: t.versions,
        currentVersionId: t.currentVersionId ?? undefined,
        context: t.context,
      });
    } catch (error) {
      log.error("Freeform autosave failed", { error });
    } finally {
      patch(threadId, (prev) => ({ ...prev, isSaving: false }));
    }
  };

  const seed = (threadId: string, record: SavedFreeform) =>
    patch(threadId, (prev) => ({
      ...prev,
      code: record.code ?? "",
      versions: record.versions ?? [],
      currentVersionId:
        record.currentVersionId ?? record.versions?.at(-1)?.id ?? null,
      templateId: record.templateId ?? prev.templateId,
      context: record.context ?? "",
    }));

  return {
    threads: {},
    threadOrder: [],

    ensureCode: (threadId, record) => {
      touch(threadId);
      evictExcessThreads();
      const cur = get().threads[threadId];
      // Once the thread has code, only refresh cheap metadata (templateId /
      // context) — never clobber the working copy. syncFromRecord handles
      // adopting a freshly-generated version.
      if (cur?.code) {
        if (
          (record.templateId && cur?.templateId !== record.templateId) ||
          (record.context !== undefined && cur?.context !== record.context)
        ) {
          patch(threadId, (prev) => ({
            ...prev,
            templateId: record.templateId ?? prev.templateId,
            context: record.context ?? prev.context,
          }));
        }
        return;
      }
      seed(threadId, record);
    },

    syncFromRecord: (threadId, record) => {
      touch(threadId);
      evictExcessThreads();
      const cur = get().threads[threadId];
      // Empty working copy → just seed.
      if (!cur || (!cur.code && cur.versions.length === 0)) {
        seed(threadId, record);
        return;
      }
      // A generation task publishes a brand-new version. If the record points at
      // a version the local copy doesn't have AND carries more history, adopt it
      // (the generation result wins over any local browsing).
      const localHasHead =
        !!record.currentVersionId &&
        cur.versions.some((v) => v.id === record.currentVersionId);
      const recordIsNewer =
        (record.versions?.length ?? 0) > cur.versions.length;
      if (record.currentVersionId && !localHasHead && recordIsNewer) {
        seed(threadId, record);
        return;
      }
      // Otherwise just keep template/context metadata fresh.
      get().ensureCode(threadId, record);
    },

    setContext: (threadId, context) => {
      patch(threadId, (prev) => ({ ...prev, context }));
    },

    commitContext: (threadId) => {
      const t = get().threads[threadId];
      if (!t) return;
      const headIdx = t.versions.findIndex((v) => v.id === t.currentVersionId);
      const head = headIdx === -1 ? undefined : t.versions[headIdx];
      // No-op if the context already matches the live version's snapshot.
      if ((head?.context ?? "") === t.context) return;
      // Coalesce consecutive context-only edits: if the head version was itself a
      // context-only edit (no prompt) on the SAME code, update it in place rather
      // than stacking a new version per pause. Otherwise append a fresh version.
      const isContextOnlyHead =
        head && !head.prompt && head.code === t.code && headIdx !== -1;
      if (isContextOnlyHead) {
        const versions = t.versions.map((v, i) =>
          i === headIdx ? { ...v, context: t.context } : v,
        );
        patch(threadId, (prev) => ({ ...prev, versions }));
      } else {
        const version: FreeformVersion = {
          id: newId(),
          code: t.code,
          context: t.context,
          createdAt: Date.now(),
        };
        // Drop any redo tail before appending (linear history, as with code edits).
        const base =
          headIdx === -1 ? t.versions : t.versions.slice(0, headIdx + 1);
        const capped =
          base.length >= MAX_VERSIONS ? base.slice(-(MAX_VERSIONS - 1)) : base;
        patch(threadId, (prev) => ({
          ...prev,
          versions: [...capped, version],
          currentVersionId: version.id,
        }));
      }
      void persist(threadId);
    },

    undo: (threadId) => {
      patch(threadId, (prev) => {
        const idx = prev.versions.findIndex(
          (v) => v.id === prev.currentVersionId,
        );
        if (idx <= 0) return prev;
        const target = prev.versions[idx - 1];
        return {
          ...prev,
          code: target.code,
          context: target.context ?? prev.context,
          currentVersionId: target.id,
        };
      });
    },

    redo: (threadId) => {
      patch(threadId, (prev) => {
        const idx = prev.versions.findIndex(
          (v) => v.id === prev.currentVersionId,
        );
        if (idx === -1 || idx >= prev.versions.length - 1) return prev;
        const target = prev.versions[idx + 1];
        return {
          ...prev,
          code: target.code,
          context: target.context ?? prev.context,
          currentVersionId: target.id,
        };
      });
    },

    setRuntimeError: (threadId, message) => {
      patch(threadId, (prev) => ({ ...prev, runtimeError: message }));
    },

    revert: (threadId) => {
      // Guard against an evicted/never-seeded thread: patch() would otherwise
      // materialize EMPTY_FREEFORM_THREAD and persist() would then save
      // code:"" over the real record — a data-loss path.
      if (!get().threads[threadId]) return;
      // Adopt the version being viewed: drop everything after it so it becomes
      // the head, then autosave.
      patch(threadId, (prev) => {
        const idx = prev.versions.findIndex(
          (v) => v.id === prev.currentVersionId,
        );
        if (idx === -1) return prev;
        return { ...prev, versions: prev.versions.slice(0, idx + 1) };
      });
      void persist(threadId);
    },

    goToLatest: (threadId) => {
      // Cancel a browse: jump to the head version (already saved, no persist).
      patch(threadId, (prev) => {
        const head = prev.versions.at(-1);
        if (!head) return prev;
        return {
          ...prev,
          code: head.code,
          context: head.context ?? prev.context,
          currentVersionId: head.id,
        };
      });
    },
  };
});

export function useFreeformThread(threadId: string): FreeformThreadState {
  return useFreeformChatStore(
    (s) => s.threads[threadId] ?? EMPTY_FREEFORM_THREAD,
  );
}
