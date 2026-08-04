import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SpacesSidebarSelectionState {
  showPreview: boolean;
  togglePreview: () => void;
}

export const useSpacesSidebarSelectionStore =
  create<SpacesSidebarSelectionState>()(
    persist(
      (set) => ({
        showPreview: false,
        togglePreview: () =>
          set((state) => ({ showPreview: !state.showPreview })),
      }),
      { name: "spaces-sidebar-selection" },
    ),
  );
