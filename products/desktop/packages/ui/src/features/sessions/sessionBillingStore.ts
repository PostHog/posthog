import type { Adapter, ModelAccess } from "@posthog/shared";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type RunBilling = Partial<Record<Adapter, ModelAccess>>;

interface SessionBillingState {
  billingByRunId: Record<string, RunBilling>;
  setBilling: (taskRunId: string, billing: RunBilling) => void;
  getBilling: (taskRunId: string) => RunBilling | undefined;
  removeBilling: (taskRunId: string) => void;
}

// A run's billing (model access) is chosen per conversation, not globally, so
// each run keeps its own choice here and reconnects resume under it.
export const useSessionBillingStore = create<SessionBillingState>()(
  persist(
    (set, get) => ({
      billingByRunId: {},
      setBilling: (taskRunId, billing) =>
        set((state) => ({
          billingByRunId: { ...state.billingByRunId, [taskRunId]: billing },
        })),
      getBilling: (taskRunId) => get().billingByRunId[taskRunId],
      removeBilling: (taskRunId) =>
        set((state) => {
          const { [taskRunId]: _removed, ...rest } = state.billingByRunId;
          return { billingByRunId: rest };
        }),
    }),
    {
      name: "session-billing-storage",
      storage: electronStorage,
      partialize: (state) => ({ billingByRunId: state.billingByRunId }),
    },
  ),
);
