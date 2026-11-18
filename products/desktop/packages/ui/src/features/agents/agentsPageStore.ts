import {
  SCOUT_DETAIL_TABS,
  type ScoutDetailTab,
} from "@posthog/core/scouts/scoutDetailTabs";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { useRouterState } from "@tanstack/react-router";
import { useMemo } from "react";

export type AgentsTab = "agents" | "memory" | "setup";

export const AGENTS_TABS: readonly AgentsTab[] = ["agents", "memory", "setup"];

interface OpenAgent {
  skillName: string;
  tab: ScoutDetailTab;
  findingId?: string;
}

export interface AgentsPageSearch {
  from?: string;
  tab?: AgentsTab;
  agent?: string;
  agentTab?: ScoutDetailTab;
  finding?: string;
}

export function agentsTabFrom(search: unknown): AgentsTab {
  const tab = (search as AgentsPageSearch | undefined)?.tab;
  return tab && AGENTS_TABS.includes(tab) ? tab : "agents";
}

export function openAgentFrom(search: unknown): OpenAgent | null {
  const value = search as AgentsPageSearch | undefined;
  if (!value?.agent) return null;
  const tab =
    value.agentTab && SCOUT_DETAIL_TABS.includes(value.agentTab)
      ? value.agentTab
      : value.finding
        ? "output"
        : "activity";
  return { skillName: value.agent, tab, findingId: value.finding };
}

export function agentsPageActions() {
  const update = (
    change: (previous: AgentsPageSearch) => AgentsPageSearch,
    replace: boolean,
  ) => {
    void getRouterOrNull()?.navigate({
      to: "/settings/$category",
      params: { category: "agents" },
      search: change,
      replace,
    });
  };
  const keepSource = ({ from }: AgentsPageSearch): AgentsPageSearch =>
    from ? { from } : {};
  return {
    showTab: (tab: AgentsTab) =>
      update((previous) => ({ ...keepSource(previous), tab }), false),
    openAgent: (
      skillName: string,
      options?: { tab?: ScoutDetailTab; findingId?: string },
    ) =>
      update(
        (previous) => ({
          ...keepSource(previous),
          agent: skillName,
          ...(options?.tab ? { agentTab: options.tab } : {}),
          ...(options?.findingId ? { finding: options.findingId } : {}),
        }),
        false,
      ),
    showAgentTab: (tab: ScoutDetailTab) =>
      update(
        (previous) =>
          previous.agent
            ? { ...previous, agentTab: tab, finding: undefined }
            : previous,
        true,
      ),
  };
}

export function useAgentsTab(): AgentsTab {
  return useRouterState({
    select: (state) => agentsTabFrom(state.location.search),
  });
}

export function useOpenAgent(): OpenAgent | null {
  const packed = useRouterState({
    select: (state) => {
      const open = openAgentFrom(state.location.search);
      return open
        ? `${open.skillName} ${open.tab} ${open.findingId ?? ""}`
        : null;
    },
  });
  return useMemo(() => {
    if (!packed) return null;
    const [skillName, tab, findingId] = packed.split(" ");
    return {
      skillName,
      tab: tab as ScoutDetailTab,
      findingId: findingId || undefined,
    };
  }, [packed]);
}

export function useAgentsPageActions() {
  return useMemo(() => agentsPageActions(), []);
}
