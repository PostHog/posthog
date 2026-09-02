import type { GatewayLimitCause } from "@posthog/shared";
import { create } from "zustand";

export interface UsageLimitShowArgs {
  resetAt?: string;
  cause?: GatewayLimitCause;
}

interface UsageLimitState {
  isOpen: boolean;
  resetAt: string | null;
  cause: GatewayLimitCause | null;
}

interface UsageLimitActions {
  show: (args?: UsageLimitShowArgs) => void;
  hide: () => void;
}

type UsageLimitStore = UsageLimitState & UsageLimitActions;

export const useUsageLimitStore = create<UsageLimitStore>()((set) => ({
  isOpen: false,
  resetAt: null,
  cause: null,

  show: (args) =>
    set({
      isOpen: true,
      resetAt: args?.resetAt ?? null,
      cause: args?.cause ?? null,
    }),
  hide: () => set({ isOpen: false }),
}));
