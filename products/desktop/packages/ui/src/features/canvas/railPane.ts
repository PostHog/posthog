import { getCurrentMatches } from "@posthog/ui/router/navigationBridge";

/**
 * Which rail destination the app is on, and whether that destination owns the
 * column beside the rail.
 *
 * The route is the only input. After the URL standardization every destination
 * owns exactly one URL root, so this table is a partition over the route tree:
 * a route the table doesn't name gets no highlight rather than a wrong one
 * (and legacy URLs never reach it — they redirect into the canonical tree).
 */
export type NavRailPane =
  | "home"
  | "spaces"
  | "activity"
  | "inbox"
  | "command-center"
  | "loops"
  | "settings";

/**
 * Route id prefixes each destination claims. Matched against the deepest route
 * in the match chain, so a destination claims its whole subtree (/inbox
 * covers /inbox/pulls/$reportId) without claiming a lookalike elsewhere
 * (/loops never covers /spaces/$channelId/loops, which is Spaces content).
 */
export const PANE_BY_ROUTE_PREFIX = [
  ["/_channels/home", "home"],
  ["/_channels/activity", "activity"],
  ["/_channels/feeds", "activity"],
  ["/command-center", "command-center"],
  ["/inbox", "inbox"],
  ["/agents", "inbox"],
  ["/loops", "loops"],
  ["/settings", "settings"],
  ["/folders", "settings"],
  ["/spaces", "spaces"],
  ["/_channels/new", "spaces"],
  ["/_channels/tasks", "spaces"],
  ["/tasks", "spaces"],
  ["/archive", "spaces"],
  ["/pr", "spaces"],
] as const;

/** No highlight is the honest answer on a route no destination owns. */
export function railPaneForRouteId(routeId: string): NavRailPane | null {
  for (const [prefix, pane] of PANE_BY_ROUTE_PREFIX) {
    if (routeId === prefix || routeId.startsWith(`${prefix}/`)) return pane;
  }
  return null;
}

export function railPaneForMatches(
  matches: readonly { routeId: string }[],
): NavRailPane {
  return (
    railPaneForRouteId(matches[matches.length - 1]?.routeId ?? "") ?? "spaces"
  );
}

/** Read the destination outside React (event handlers, imperative picks). */
export function getRailPane(): NavRailPane {
  return railPaneForMatches(getCurrentMatches());
}

// Home, Inbox, Command Center, Loops and Settings are whole-screen
// destinations: no route under them puts a second nav on the screen. Spaces
// owns the space tree, Activity owns the feed.
export const PANES_WITH_SIDEBAR = new Set<NavRailPane>(["spaces", "activity"]);

export function railPaneHasSidebar(pane: NavRailPane): boolean {
  return PANES_WITH_SIDEBAR.has(pane);
}
