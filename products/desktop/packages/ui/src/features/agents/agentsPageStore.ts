import type { ScoutDetailTab } from "@posthog/core/scouts/scoutDetailTabs";
import { create } from "zustand";

export type AgentsTab = "agents" | "signals" | "memory" | "setup";

interface OpenAgent {
  slug: string;
  tab: ScoutDetailTab;
  /** Emission id from a shared finding link — expanded when the page opens. */
  findingId?: string;
}

interface AgentsPageState {
  tab: AgentsTab;
  agent: OpenAgent | null;
}

interface AgentsPageActions {
  showTab: (tab: AgentsTab) => void;
  openAgent: (
    slug: string,
    options?: { tab?: ScoutDetailTab; findingId?: string },
  ) => void;
  showAgentTab: (tab: ScoutDetailTab) => void;
}

type AgentsPageStore = AgentsPageState & { actions: AgentsPageActions };

// The Agents page is a settings category, so it has no URL of its own below
// /settings/agents. Which tab is open, and which agent, live here instead.
const useStore = create<AgentsPageStore>((set) => ({
  tab: "agents",
  agent: null,
  actions: {
    showTab: (tab) => set({ tab, agent: null }),
    openAgent: (slug, options) =>
      set({
        tab: "agents",
        agent: {
          slug,
          tab: options?.tab ?? (options?.findingId ? "signals" : "activity"),
          findingId: options?.findingId,
        },
      }),
    showAgentTab: (tab) =>
      set((state) =>
        state.agent
          ? { agent: { ...state.agent, tab, findingId: undefined } }
          : state,
      ),
  },
}));

export const useAgentsTab = () => useStore((s) => s.tab);
export const useOpenAgent = () => useStore((s) => s.agent);
export const useAgentsPageActions = () => useStore((s) => s.actions);
export const agentsPageActions = () => useStore.getState().actions;
