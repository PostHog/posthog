import { create } from "zustand";

interface SidebarSearchState {
  focusRequest: number;
  requestFocus: () => void;
}

export const useSidebarSearchStore = create<SidebarSearchState>()((set) => ({
  focusRequest: 0,
  requestFocus: () =>
    set((state) => ({ focusRequest: state.focusRequest + 1 })),
}));

export function requestSidebarSearchFocus(): void {
  useSidebarSearchStore.getState().requestFocus();
}
