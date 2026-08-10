import { create } from "zustand";

interface MissionControlStore {
  active: boolean;
  setActive: (active: boolean) => void;
}

/**
 * Whether the branded Mission Control overlay is showing. Deliberately not
 * persisted: it describes what the window is doing right now, and restoring it
 * across a restart would leave the overlay stuck on.
 */
export const useMissionControlStore = create<MissionControlStore>()((set) => ({
  active: false,
  setActive: (active) => set({ active }),
}));
