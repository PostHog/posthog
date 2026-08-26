import type { AgentFlowDefinition } from "@posthog/shared";
import {
  electronStorage,
  flushRendererStateWrites,
} from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface AgentFlowRecord extends AgentFlowDefinition {
  identity: string;
  createdAt: number;
  updatedAt: number;
}

interface AgentFlowState {
  flows: AgentFlowRecord[];
  _hasHydrated: boolean;
  saveFlow: (identity: string, flow: AgentFlowDefinition) => void;
  deleteFlow: (identity: string, flowId: string) => void;
  setHasHydrated: (hydrated: boolean) => void;
}

export const useAgentFlowStore = create<AgentFlowState>()(
  persist(
    (set) => ({
      flows: [],
      _hasHydrated: false,
      saveFlow: (identity, flow) => {
        const now = Date.now();
        set((state) => {
          const existing = state.flows.find(
            (item) => item.identity === identity && item.id === flow.id,
          );
          const saved: AgentFlowRecord = {
            ...flow,
            identity,
            createdAt: existing?.createdAt ?? now,
            updatedAt: now,
          };
          return {
            flows: [
              saved,
              ...state.flows.filter(
                (item) => item.identity !== identity || item.id !== flow.id,
              ),
            ],
          };
        });
        void flushRendererStateWrites();
      },
      deleteFlow: (identity, flowId) => {
        set((state) => ({
          flows: state.flows.filter(
            (item) => item.identity !== identity || item.id !== flowId,
          ),
        }));
        void flushRendererStateWrites();
      },
      setHasHydrated: (hydrated) => set({ _hasHydrated: hydrated }),
    }),
    {
      name: "posthog-code-agent-flows",
      storage: electronStorage,
      partialize: (state) => ({ flows: state.flows }),
      version: 1,
      migrate: () => ({ flows: [] as AgentFlowRecord[] }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.setHasHydrated(true);
          return;
        }
        useAgentFlowStore.setState({ _hasHydrated: true });
      },
    },
  ),
);
