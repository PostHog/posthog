import { createStore } from "zustand/vanilla";

export type PlatformStatus = {
  status:
    | "operational"
    | "degraded_performance"
    | "partial_outage"
    | "major_outage"
    | "unknown";
  statusPageUrl: string;
};

export const UNKNOWN_PLATFORM_STATUS: PlatformStatus = {
  status: "unknown",
  statusPageUrl: "https://www.posthogstatus.com",
};

type PlatformStatusState = {
  status: PlatformStatus;
  setStatus: (status: PlatformStatus) => void;
};

export const platformStatusStore = createStore<PlatformStatusState>((set) => ({
  status: UNKNOWN_PLATFORM_STATUS,
  setStatus: (status) => set({ status }),
}));
