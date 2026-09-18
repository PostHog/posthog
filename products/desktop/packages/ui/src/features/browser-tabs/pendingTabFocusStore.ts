import { create } from "zustand";

interface PendingTabFocusStore {
  tabId: string | null;
  setPending: (tabId: string | null) => void;
}

export const usePendingTabFocusStore = create<PendingTabFocusStore>((set) => ({
  tabId: null,
  setPending: (tabId) =>
    set((state) => (state.tabId === tabId ? state : { tabId })),
}));
