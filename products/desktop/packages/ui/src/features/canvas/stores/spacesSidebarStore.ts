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
  toggle: (channelId: string) => void;
  toggleAddSpace: () => void;
  toggleOnlyMyTasks: () => void;
}

export const useSpacesSidebarStore = create<SpacesSidebarState>()(
  persist(
    (set) => ({
      openSections: {},
      // Open by default: with nothing pinned yet, a collapsed directory left
      // the sidebar looking empty. Returning users keep whatever they chose.
      openAddSpace: true,
      onlyMyTasks: false,
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
    }),
    { name: "spaces-sidebar" },
  ),
);
