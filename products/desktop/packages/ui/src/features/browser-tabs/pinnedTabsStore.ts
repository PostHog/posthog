import { create } from "zustand";
import { persist } from "zustand/middleware";

const STORAGE_KEY = "browser-tabs-pinned-storage";

/**
 * Pinned browser tabs — pure view state persisted to localStorage, keyed by
 * tab id (tab ids are durable in SQLite, so pins survive relaunch). Pinned
 * tabs sort to the front of the strip, lose their hover-close affordance, and
 * are excluded from the bulk close operations (close others / to the right /
 * to the left).
 *
 * Pins are a per-origin view concern, not domain state — the desktop app is
 * single-window, so a live cross-window sync isn't required. For the web host
 * (multiple browser tabs share the origin), a storage-event listener keeps
 * renderers roughly in step; the authoritative order still lives in the
 * (pin-agnostic) SQLite snapshot.
 */
interface PinnedTabsStore {
  pinnedTabIds: string[];
  togglePinned: (tabId: string) => void;
  /** Drop pins whose tab no longer exists so the list doesn't accumulate. */
  prune: (liveTabIds: string[]) => void;
}

export const usePinnedTabsStore = create<PinnedTabsStore>()(
  persist(
    (set) => ({
      pinnedTabIds: [],
      togglePinned: (tabId) =>
        set((state) => ({
          pinnedTabIds: state.pinnedTabIds.includes(tabId)
            ? state.pinnedTabIds.filter((id) => id !== tabId)
            : [...state.pinnedTabIds, tabId],
        })),
      prune: (liveTabIds) =>
        set((state) => {
          const live = new Set(liveTabIds);
          const next = state.pinnedTabIds.filter((id) => live.has(id));
          return next.length === state.pinnedTabIds.length
            ? state
            : { pinnedTabIds: next };
        }),
    }),
    { name: STORAGE_KEY },
  ),
);

// zustand/persist only reads storage at load; mirror another same-origin
// renderer's writes so open web tabs don't diverge (no-op on desktop).
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== STORAGE_KEY || !e.newValue) return;
    try {
      const ids = JSON.parse(e.newValue)?.state?.pinnedTabIds;
      if (Array.isArray(ids))
        usePinnedTabsStore.setState({ pinnedTabIds: ids });
    } catch {
      // Ignore malformed payloads from another tab.
    }
  });
}
