import { create } from "zustand";

export const useClassicViewStore = create<{
  revision: number;
  openDashboards: () => void;
}>((set) => ({
  revision: 0,
  openDashboards: () => set((state) => ({ revision: state.revision + 1 })),
}));
