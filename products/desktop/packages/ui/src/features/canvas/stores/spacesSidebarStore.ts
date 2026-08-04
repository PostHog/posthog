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
  setOpen: (channelId: string, open: boolean) => void;
  toggle: (channelId: string) => void;
  toggleAddSpace: () => void;
}

export const useSpacesSidebarStore = create<SpacesSidebarState>()(
  persist(
    (set) => ({
      openSections: {},
      openAddSpace: false,
      setOpen: (channelId, open) =>
        set((state) => ({
          openSections: { ...state.openSections, [channelId]: open },
        })),
      toggle: (channelId) =>
        set((state) => ({
          openSections: {
            ...state.openSections,
            [channelId]: !state.openSections[channelId],
          },
        })),
      toggleAddSpace: () =>
        set((state) => ({ openAddSpace: !state.openAddSpace })),
    }),
    { name: "spaces-sidebar" },
  ),
);
