import type { BrowserTab, TabsSnapshot } from "@posthog/shared";

export function requestTabSelection(
  snapshot: TabsSnapshot,
  windowId: string,
  tabId: string,
  navigate: (tab: BrowserTab) => void,
): void {
  const target = snapshot.tabs.find(
    (tab) => tab.windowId === windowId && tab.id === tabId,
  );
  if (target) navigate(target);
}
