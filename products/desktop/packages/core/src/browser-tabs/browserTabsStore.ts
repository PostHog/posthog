import type { TabsSnapshot } from "@posthog/shared";
import { createStore } from "zustand/vanilla";

/**
 * Renderer-side mirror of the authoritative tab/window snapshot owned by the
 * main-process BrowserTabsService. Seeded once and kept live via the
 * snapshot-change subscription, so every window reflects one source of truth.
 */
interface BrowserTabsState {
  snapshot: TabsSnapshot;
  setSnapshot: (snapshot: TabsSnapshot) => void;
}

// True when two snapshots carry the same value. Reference check first (the
// common no-op), then a structural compare. Stringify can only yield a false
// *mismatch* (e.g. key-order drift), never a false match — so it can bail on a
// redundant write but never skip a real change, which would strand a stale
// mirror.
function snapshotsEqual(a: TabsSnapshot, b: TabsSnapshot): boolean {
  return a === b || JSON.stringify(a) === JSON.stringify(b);
}

export const browserTabsStore = createStore<BrowserTabsState>((set) => ({
  snapshot: { windows: [], tabs: [] },
  // Skip redundant writes: every tab mutation's onSuccess re-applies the
  // authoritative snapshot even when an optimistic write already set an equal
  // value. Without this guard that echo re-renders every subscriber and re-runs
  // the navigation effect (which depends on this snapshot) for no change.
  setSnapshot: (snapshot) =>
    set((prev) =>
      snapshotsEqual(prev.snapshot, snapshot) ? prev : { snapshot },
    ),
}));

export const getTabsSnapshot = () => browserTabsStore.getState().snapshot;
