import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The space list's tree state: which spaces are expanded to show their recent
 * tasks.
 *
 * Expansion persists — a space you opened to keep an eye on is still open after
 * a restart.
 */
interface SpaceTreeState {
  expandedSpaceIds: Set<string>;
  /**
   * The row the keyboard is on, so a session row can open its card as the
   * highlight lands on it. Not persisted. Only the rows read it, each through a
   * boolean selector, so a keypress re-renders the two rows whose answer
   * changed instead of the whole list.
   */
  highlightedValue: string | undefined;
  toggleSpace: (spaceId: string) => void;
  expandSpace: (spaceId: string) => void;
  collapseSpace: (spaceId: string) => void;
  setHighlightedValue: (value: string | undefined) => void;
}

export const useSpaceTreeStore = create<SpaceTreeState>()(
  persist(
    (set) => ({
      expandedSpaceIds: new Set<string>(),
      highlightedValue: undefined,
      toggleSpace: (spaceId) =>
        set((state) => {
          const expanded = new Set(state.expandedSpaceIds);
          if (!expanded.delete(spaceId)) expanded.add(spaceId);
          return { expandedSpaceIds: expanded };
        }),
      expandSpace: (spaceId) =>
        set((state) => {
          if (state.expandedSpaceIds.has(spaceId)) return state;
          return {
            expandedSpaceIds: new Set(state.expandedSpaceIds).add(spaceId),
          };
        }),
      collapseSpace: (spaceId) =>
        set((state) => {
          if (!state.expandedSpaceIds.has(spaceId)) return state;
          const expanded = new Set(state.expandedSpaceIds);
          expanded.delete(spaceId);
          return { expandedSpaceIds: expanded };
        }),
      setHighlightedValue: (value) =>
        set((state) =>
          state.highlightedValue === value
            ? state
            : { highlightedValue: value },
        ),
    }),
    {
      name: "space-tree-storage",
      // A Set doesn't survive JSON, so it's stored as an array and rebuilt on
      // load — the same shape sidebarStore uses for its collapsed sections.
      partialize: (state) => ({
        expandedSpaceIds: Array.from(state.expandedSpaceIds),
      }),
      merge: (persisted, current) => ({
        ...current,
        expandedSpaceIds: new Set(
          (persisted as { expandedSpaceIds?: string[] })?.expandedSpaceIds ??
            [],
        ),
      }),
    },
  ),
);
