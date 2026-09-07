import type { TabIdentity, TabLocation } from "@posthog/shared";
import { create } from "zustand";

/** A closed tab's restorable location. `href` is what a reopen navigates to,
 * so a tab without one is never recorded. */
export type ClosedTab = TabLocation & TabIdentity & { href: string };

/** How far back Cmd/Ctrl+Shift+T walks. Deliberately small: the stack is a
 * remedy for a mis-click, not a session archive. */
export const MAX_CLOSED_TABS = 10;

/**
 * The recently-closed browser tabs, newest last — the stack behind
 * Cmd/Ctrl+Shift+T.
 *
 * View state, not domain state: it lives only in the renderer and only for the
 * session. Persisting it would fight tab restore, which already brings back
 * every tab that was open at quit, so a reopen after a relaunch could mint a
 * second copy of a tab already on screen.
 */
interface ClosedTabsStore {
  closed: ClosedTab[];
  /** Push the tabs a close removed, in the order they were closed. */
  record: (tabs: ClosedTab[]) => void;
  /** Pop the most recently closed tab. */
  take: () => ClosedTab | null;
}

export const useClosedTabsStore = create<ClosedTabsStore>((set, get) => ({
  closed: [],
  record: (tabs) => {
    if (tabs.length === 0) return;
    set((state) => ({
      closed: [...state.closed, ...tabs].slice(-MAX_CLOSED_TABS),
    }));
  },
  take: () => {
    const { closed } = get();
    const last = closed[closed.length - 1];
    if (!last) return null;
    set({ closed: closed.slice(0, -1) });
    return last;
  },
}));

/** Read a tab's restorable record, or null when it has nothing to restore. */
export function closedTabRecord(
  tab: TabLocation & TabIdentity,
): ClosedTab | null {
  if (!tab.href) return null;
  return {
    href: tab.href,
    viewState: tab.viewState,
    dashboardId: tab.dashboardId,
    taskId: tab.taskId,
    channelId: tab.channelId,
    channelSection: tab.channelSection,
    appView: tab.appView,
  };
}
