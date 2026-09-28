import type { LibraryLoadOutcome } from "@posthog/shared/analytics-events";
import { create } from "zustand";

export type LibraryIslandStatus =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "mounted" }
  | {
      state: "failed";
      reason: Exclude<LibraryLoadOutcome, "mounted" | "unavailable">;
    };

interface LibraryIslandStore {
  status: LibraryIslandStatus;
  setStatus: (status: LibraryIslandStatus) => void;
}

export const useLibraryIslandStore = create<LibraryIslandStore>()((set) => ({
  status: { state: "idle" },
  setStatus: (status) => set({ status }),
}));
