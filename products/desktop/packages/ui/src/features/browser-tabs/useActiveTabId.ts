import { primaryWindow } from "@posthog/shared";
import { useTileLayoutStore } from "@posthog/ui/features/tab-tiling/tileLayoutStore";
import {
  groupForTab,
  lastActiveIn,
} from "@posthog/ui/features/tab-tiling/tileTree";
import { useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";
import { usePendingTabFocusStore } from "./pendingTabFocusStore";
import { useTabsSnapshot } from "./useBrowserTabs";

export function useActiveTabId(): string | null {
  const snapshot = useTabsSnapshot();
  const historyTabId = useRouterState({
    select: (s) => s.location.state.tabId ?? null,
  });
  const pendingTabId = usePendingTabFocusStore((s) => s.tabId);
  const setPending = usePendingTabFocusStore((s) => s.setPending);
  const groups = useTileLayoutStore((s) => s.groups);
  const activeByGroup = useTileLayoutStore((s) => s.activeByGroup);

  useEffect(() => {
    if (pendingTabId && historyTabId === pendingTabId) setPending(null);
  }, [historyTabId, pendingTabId, setPending]);

  const isLive = (tabId: string | null): tabId is string =>
    tabId !== null && snapshot.tabs.some((t) => t.id === tabId);
  const focusedIn = (tabId: string): string => {
    const group = groupForTab(groups, tabId);
    return group ? lastActiveIn(group, activeByGroup) : tabId;
  };
  if (isLive(pendingTabId)) return focusedIn(pendingTabId);
  if (isLive(historyTabId)) return focusedIn(historyTabId);
  const windowActive = primaryWindow(snapshot)?.activeTabId ?? null;
  return isLive(windowActive) ? focusedIn(windowActive) : null;
}
