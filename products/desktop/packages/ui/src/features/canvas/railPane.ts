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
  | "loops"
  | "context";

/**
 * The root path of each destination.
 *
 * Matched against the deepest match's `fullPath` — the route's own pattern, not
 * the resolved URL — so a destination claims its whole subtree (`/inbox` covers
 * `/inbox/pulls/$reportId`) and no space id can ever impersonate one.
 */
export const RAIL_PANE_ROOT: Readonly<Record<NavRailPane, string>> = {
  home: "/",
  spaces: "/spaces",
  activity: "/activity",
  inbox: "/inbox",
  "command-center": "/command-center",
  loops: "/loops",
  context: "/spaces/context",
};

// Spaces is absent: it takes everything nothing else claims, so listing it
// would only shadow that fallback with the same answer.
const CLAIMED: readonly NavRailPane[] = [
  "home",
  "activity",
  "inbox",
  "command-center",
  "loops",
  "context",
];

export function railPaneForPath(fullPath: string): NavRailPane {
  for (const pane of CLAIMED) {
    const root = RAIL_PANE_ROOT[pane];
    if (fullPath === root) return pane;
    // Home is exact-only: every path starts with "/", so a prefix test would
    // hand it every route in the app.
    if (root !== "/" && fullPath.startsWith(`${root}/`)) return pane;
  }
  // Unclaimed routes belong to Spaces — the app's resting destination.
  return "spaces";
}

export function railPaneForMatches(
  matches: readonly { fullPath: string }[],
): NavRailPane {
  return railPaneForPath(matches[matches.length - 1]?.fullPath ?? "");
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
