import { getCurrentMatches } from "@posthog/ui/router/navigationBridge";

/**
 * Which rail destination the app is on, and whether that destination owns the
 * column beside the rail.
 *
 * The route is the only input. A destination the user could be "on" without the
 * URL saying so is what let the sidebar and the screen disagree — Home wearing
 * the space list, Activity drawn twice, a space page with no space nav.
 */
export type NavRailPane =
  | "home"
  | "spaces"
  | "activity"
  | "inbox"
  | "command-center"
  | "loops";

/**
 * Route id prefixes each destination claims. Matched against the deepest route
 * in the match chain, so a destination claims its whole subtree (/code/inbox
 * covers /code/inbox/pulls/$reportId) without claiming a lookalike elsewhere
 * (/code/loops never covers /website/$channelId/loops).
 */
const PANE_BY_ROUTE_PREFIX: readonly (readonly [string, NavRailPane])[] = [
  ["/website/home", "home"],
  ["/website/activity", "activity"],
  ["/website/command-center", "command-center"],
  ["/command-center", "command-center"],
  ["/code/inbox", "inbox"],
  ["/code/loops", "loops"],
];

/** Unclaimed routes belong to Spaces — the app's resting destination. */
export function railPaneForRouteId(routeId: string): NavRailPane {
  for (const [prefix, pane] of PANE_BY_ROUTE_PREFIX) {
    if (routeId === prefix || routeId.startsWith(`${prefix}/`)) return pane;
  }
  return "spaces";
}

export function railPaneForMatches(
  matches: readonly { routeId: string }[],
): NavRailPane {
  return railPaneForRouteId(matches[matches.length - 1]?.routeId ?? "");
}

/** Read the destination outside React (event handlers, imperative picks). */
export function getRailPane(): NavRailPane {
  return railPaneForMatches(getCurrentMatches());
}

// Home, Inbox, Command Center and Loops are whole-screen destinations: no
// route under them may put a second nav on the screen. Spaces owns the space
// tree, Activity owns the feed.
const PANES_WITH_SIDEBAR = new Set<NavRailPane>(["spaces", "activity"]);

export function railPaneHasSidebar(pane: NavRailPane): boolean {
  return PANES_WITH_SIDEBAR.has(pane);
}
