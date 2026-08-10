import { create } from "zustand";

interface MissionControlStore {
  active: boolean;
  setActive: (active: boolean) => void;
}

/** Not persisted: restoring it across a restart would leave the overlay stuck on. */
export const useMissionControlStore = create<MissionControlStore>()((set) => ({
  active: false,
  setActive: (active) => set({ active }),
}));
