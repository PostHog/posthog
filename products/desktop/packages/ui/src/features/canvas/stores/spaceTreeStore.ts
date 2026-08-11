import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * The space list's tree state: which spaces are expanded to show their recent
 * tasks, plus the request to put the keyboard back in the search box.
 *
 * Expansion persists — a space you opened to keep an eye on is still open after
 * a restart. The focus request is a counter rather than a boolean because it is
 * an event, not a state: pressing the shortcut twice in a row has to reach the
 * list twice.
 */
interface SpaceTreeState {
  expandedSpaceIds: Set<string>;
  searchFocusRequest: number;
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
  requestSearchFocus: () => void;
  setHighlightedValue: (value: string | undefined) => void;
}

export const useSpaceTreeStore = create<SpaceTreeState>()(
  persist(
    (set) => ({
      expandedSpaceIds: new Set<string>(),
      searchFocusRequest: 0,
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
      requestSearchFocus: () =>
        set((state) => ({ searchFocusRequest: state.searchFocusRequest + 1 })),
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

/**
 * Ask the space list to take the keyboard — the ⌘⇧S shortcut's half of the job,
 * the list itself owns the focus.
 */
export function requestSpaceSearchFocus(): void {
  useSpaceTreeStore.getState().requestSearchFocus();
}
