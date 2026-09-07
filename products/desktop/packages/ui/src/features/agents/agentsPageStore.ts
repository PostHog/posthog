import type { ScoutDetailTab } from "@posthog/core/scouts/scoutDetailTabs";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";
import { create } from "zustand";

export type AgentsTab = "agents" | "memory" | "setup";

interface OpenAgent {
  slug: string;
  tab: ScoutDetailTab;
  findingId?: string;
}

interface AgentsPageState {
  tab: AgentsTab;
  agent: OpenAgent | null;
}

const DEFAULT_STATE: AgentsPageState = { tab: "agents", agent: null };
const useStore = create<{ pages: Record<string, AgentsPageState> }>(() => ({
  pages: {},
}));

function usePageKey(): string {
  return useRouterState({
    select: (state) => state.location.state.tabId ?? "default",
  });
}

export function agentsPageActions(
  key = getRouterOrNull()?.history.location.state.tabId ?? "default",
) {
  const update = (change: (state: AgentsPageState) => AgentsPageState) => {
    useStore.setState((state) => ({
      pages: {
        ...state.pages,
        [key]: change(state.pages[key] ?? DEFAULT_STATE),
      },
    }));
  };
  return {
    showTab: (tab: AgentsTab) => update(() => ({ tab, agent: null })),
    openAgent: (
      slug: string,
      options?: { tab?: ScoutDetailTab; findingId?: string },
    ) =>
      update(() => ({
        tab: "agents",
        agent: {
          slug,
          tab: options?.tab ?? (options?.findingId ? "output" : "activity"),
          findingId: options?.findingId,
        },
      })),
    showAgentTab: (tab: ScoutDetailTab) =>
      update((state) =>
        state.agent
          ? { ...state, agent: { ...state.agent, tab, findingId: undefined } }
          : state,
      ),
  };
}

export function useAgentsTab() {
  const key = usePageKey();
  return useStore((state) => (state.pages[key] ?? DEFAULT_STATE).tab);
}

export function useOpenAgent() {
  const key = usePageKey();
  return useStore((state) => (state.pages[key] ?? DEFAULT_STATE).agent);
}

export function useAgentsPageActions() {
  const key = usePageKey();
  return useMemo(() => agentsPageActions(key), [key]);
}
