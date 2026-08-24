import type { NavRailPane } from "@posthog/ui/features/canvas/railPane";
import { create } from "zustand";

/**
 * The sidebar state a space visit has on top of its route: whether the space
 * list was drawn over the space pane, and the space it was drawn over. That is
 * view state rather than a route, so the href alone cannot bring it back.
 */
export interface SpacesVisitView {
  listOpen: boolean;
  /** Absent on the space index and other unscoped routes. */
  spaceId?: string;
}

export interface RailVisit {
  /** The concrete href, so a pick returns to the page, not the destination. */
  href: string;
  /** Set only for Spaces — no other destination has a sidebar pane to restore. */
  spaces?: SpacesVisitView;
}

interface RailHistoryState {
  lastByPane: Partial<Record<NavRailPane, RailVisit>>;
  record: (pane: NavRailPane, visit: RailVisit) => void;
}

/**
 * Where each rail destination was when you last left it.
 *
 * Session-scoped on purpose: `startupLocation` already reopens the app on the
 * route you quit, so persisting this would compete with it on launch and hand
 * you a week-old inbox report behind a destination you had moved on from.
 */
export const useRailHistoryStore = create<RailHistoryState>()((set) => ({
  lastByPane: {},
  record: (pane, visit) =>
    set((state) => ({ lastByPane: { ...state.lastByPane, [pane]: visit } })),
}));

/**
 * Forget every remembered destination. Called on logout and project switch
 * (beside `resetCurrentChannel`) because a visit holds hrefs and space ids from
 * the current project; without this a rail pick after a switch would restore a
 * page — or re-scope the app to a space — from the project the user just left.
 */
export function resetRailHistory(): void {
  useRailHistoryStore.setState({ lastByPane: {} });
}
