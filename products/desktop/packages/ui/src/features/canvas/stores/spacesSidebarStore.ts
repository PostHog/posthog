import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * View state for the static spaces sidebar: which space sections are expanded.
 * Unexpanded is the default (mock shows collapse chevron-down for the first
 * space only), so the map stores explicit expansions. `openAgents` toggles the
 * pinned-agents placeholder section.
 */
interface SpacesSidebarState {
  openSections: Record<string, boolean>;
  openAgents: boolean;
  setOpen: (channelId: string, open: boolean) => void;
  toggle: (channelId: string) => void;
  toggleAgents: () => void;
}

export const useSpacesSidebarStore = create<SpacesSidebarState>()(
  persist(
    (set) => ({
      openSections: {},
      openAgents: false,
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
      toggleAgents: () => set((state) => ({ openAgents: !state.openAgents })),
    }),
    { name: "spaces-sidebar" },
  ),
);
