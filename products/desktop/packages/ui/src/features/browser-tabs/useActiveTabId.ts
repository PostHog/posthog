import { primaryWindow } from "@posthog/shared";
import { useTileLayoutStore } from "@posthog/ui/features/tab-tiling/tileLayoutStore";
import { focusedTabIn } from "@posthog/ui/features/tab-tiling/tileTree";
import { useRouterState } from "@tanstack/react-router";
import { useTabsSnapshot } from "./useBrowserTabs";

export function useActiveTabId(): string | null {
  const snapshot = useTabsSnapshot();
  const historyTabId = useRouterState({
    select: (s) => s.location.state.tabId ?? null,
  });
  const groups = useTileLayoutStore((s) => s.groups);
  const activeByGroup = useTileLayoutStore((s) => s.activeByGroup);
  const isLive = (tabId: string | null): tabId is string =>
    tabId !== null && snapshot.tabs.some((t) => t.id === tabId);
  const tabId = isLive(historyTabId)
    ? historyTabId
    : (primaryWindow(snapshot)?.activeTabId ?? null);
  return isLive(tabId) ? focusedTabIn(groups, activeByGroup, tabId) : null;
}
