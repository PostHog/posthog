import { create } from "zustand";

interface MissionControlStore {
  active: boolean;
  setActive: (active: boolean) => void;
}

export const useMissionControlStore = create<MissionControlStore>()((set) => ({
  active: false,
  setActive: (active) => set({ active }),
}));
