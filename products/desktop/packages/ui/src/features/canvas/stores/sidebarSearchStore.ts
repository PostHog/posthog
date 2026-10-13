import { create } from "zustand";

interface SidebarSearchState {
  focusRequest: number;
  requestFocus: () => void;
  claimFocus: (token: number) => boolean;
}

export const useSidebarSearchStore = create<SidebarSearchState>()(
  (set, get) => ({
    focusRequest: 0,
    requestFocus: () =>
      set((state) => ({ focusRequest: state.focusRequest + 1 })),
    // Consume a focus request so it fires once. Without this a stale request
    // stays pending and steals the keyboard when any header later mounts, such
    // as the Activity rail hover popover.
    claimFocus: (token) => {
      if (token === 0 || get().focusRequest !== token) return false;
      set({ focusRequest: 0 });
      return true;
    },
  }),
);

export function requestSidebarSearchFocus(): void {
  useSidebarSearchStore.getState().requestFocus();
}
