import type { RouterHistory } from "@tanstack/react-router";

declare module "@tanstack/history" {
  interface HistoryState {
    tabId?: string;
  }
}

/**
 * Select a tab by identity, even when it has the same href as the active tab.
 * Router-level navigate may collapse a same-href navigation and retain the old
 * tabId, which makes two tabs showing the same page impossible to select.
 */
export function pushTabHistoryEntry(
  history: RouterHistory,
  href: string,
  tabId: string,
): void {
  history.push(href, { ...history.location.state, tabId });
}
