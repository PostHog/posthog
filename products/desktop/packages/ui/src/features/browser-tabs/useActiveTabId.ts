import { primaryWindow } from "@posthog/shared";
import { useRouterState } from "@tanstack/react-router";
import { useTabsSnapshot } from "./useBrowserTabs";

export function useActiveTabId(): string | null {
  const snapshot = useTabsSnapshot();
  const historyTabId = useRouterState({
    select: (s) => s.location.state.tabId ?? null,
  });
  if (historyTabId && snapshot.tabs.some((t) => t.id === historyTabId)) {
    return historyTabId;
  }
  return primaryWindow(snapshot)?.activeTabId ?? null;
}
