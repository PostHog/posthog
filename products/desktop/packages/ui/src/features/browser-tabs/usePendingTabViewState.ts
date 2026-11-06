import { primaryWindow, type TabViewState } from "@posthog/shared";
import { useRouterState } from "@tanstack/react-router";
import { useTabsSnapshot } from "./useBrowserTabs";

type PendingTabViewState = {
  isPending: boolean;
  viewState: TabViewState | null;
};

/**
 * The destination tab's sidebar state while its route is still settling.
 * Rendering may follow the in-flight history tag immediately, but durable tab
 * focus and the window-global sidebar stores remain settled-navigation writes.
 */
export function usePendingTabViewState(): PendingTabViewState {
  const snapshot = useTabsSnapshot();
  const historyTabId = useRouterState({
    select: (state) => state.location.state.tabId,
  });
  const window = primaryWindow(snapshot);

  if (!window || !historyTabId || historyTabId === window.activeTabId) {
    return { isPending: false, viewState: null };
  }

  const target = snapshot.tabs.find(
    (tab) => tab.id === historyTabId && tab.windowId === window.id,
  );
  return {
    isPending: target !== undefined,
    viewState: target?.viewState ?? null,
  };
}
