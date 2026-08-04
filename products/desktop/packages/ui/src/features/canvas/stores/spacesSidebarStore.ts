import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * View state for the static spaces sidebar: per-space expands, and the
 * "All spaces" list toggle. `openSections` stores explicit space expansion
 * (default collapsed); `openAddSpace` stores the all-spaces list toggle.
 */
interface SpacesSidebarState {
  openSections: Record<string, boolean>;
  openAddSpace: boolean;
  /** Narrow every space's task list to items the viewer created. */
  onlyMyTasks: boolean;
  /**
   * The user's drag-reorder of the pinned spaces (channel ids, first = top).
   * A local view preference layered over the starred set: spaces not listed
   * here keep their backend order after the ranked ones; #me is always first
   * and never ranked.
   */
  spaceOrder: string[];
  /** The watch list section's fold. */
  openWatchList: boolean;
  /**
   * Task ids the user dragged into the watch list, newest first. Local-only
   * references for now — watching doesn't touch the task or its space.
   */
  watchList: string[];
  toggle: (channelId: string) => void;
  toggleAddSpace: () => void;
  toggleOnlyMyTasks: () => void;
  toggleWatchList: () => void;
  setSpaceOrder: (ids: string[]) => void;
  addToWatchList: (taskId: string) => void;
  removeFromWatchList: (taskId: string) => void;
}

export const useSpacesSidebarStore = create<SpacesSidebarState>()(
  persist(
    (set) => ({
      openSections: {},
      // Open by default: with nothing pinned yet, a collapsed directory left
      // the sidebar looking empty. Returning users keep whatever they chose.
      openAddSpace: true,
      onlyMyTasks: false,
      spaceOrder: [],
      openWatchList: true,
      watchList: [],
      toggle: (channelId) =>
        set((state) => ({
          openSections: {
            ...state.openSections,
            [channelId]: !state.openSections[channelId],
          },
        })),
      toggleAddSpace: () =>
        set((state) => ({ openAddSpace: !state.openAddSpace })),
      toggleOnlyMyTasks: () =>
        set((state) => ({ onlyMyTasks: !state.onlyMyTasks })),
      toggleWatchList: () =>
        set((state) => ({ openWatchList: !state.openWatchList })),
      setSpaceOrder: (ids) => set({ spaceOrder: ids }),
      addToWatchList: (taskId) =>
        set((state) => ({
          watchList: [taskId, ...state.watchList.filter((id) => id !== taskId)],
        })),
      removeFromWatchList: (taskId) =>
        set((state) => ({
          watchList: state.watchList.filter((id) => id !== taskId),
        })),
    }),
    { name: "spaces-sidebar" },
  ),
);
