/**
 * The chrome's panel state, carried in the URL so any exact view is shareable
 * and restorable. Widths stay in persisted stores — they'd churn the URL on
 * every drag. All params are optional; their absence is the default state
 * (secondary panel follows the route, right panel closed).
 */

/** Tab inside a space's secondary panel. */
export type SpacePanelTab = "sessions" | "loops" | "artifacts";

/** Which right panel is open. `changes` also opens via reviewNavigationStore. */
export type RightPanelSide = "artifacts" | "comments" | "changes";

/**
 * `panel` selects the secondary panel: absent follows the route (a space route
 * shows that space's panel), "activity" pins the activity feed regardless of
 * route, "off" closes it for the current destination.
 */
export type SecondaryPanelParam = "activity" | "off";

export interface NavPanelSearch {
  panel?: SecondaryPanelParam;
  stab?: SpacePanelTab;
  side?: RightPanelSide;
}

const PANEL_VALUES: readonly SecondaryPanelParam[] = ["activity", "off"];
const SPACE_TAB_VALUES: readonly SpacePanelTab[] = [
  "sessions",
  "loops",
  "artifacts",
];
const SIDE_VALUES: readonly RightPanelSide[] = [
  "artifacts",
  "comments",
  "changes",
];

function oneOf<T extends string>(
  value: unknown,
  values: readonly T[],
): T | undefined {
  return typeof value === "string" &&
    (values as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

/** Drops anything that isn't a known value, so a hand-edited or stale URL
 *  degrades to defaults instead of rendering an impossible panel state. */
export function validateNavPanelSearch(
  search: Record<string, unknown>,
): NavPanelSearch {
  const panel = oneOf(search.panel, PANEL_VALUES);
  const stab = oneOf(search.stab, SPACE_TAB_VALUES);
  const side = oneOf(search.side, SIDE_VALUES);
  const result: NavPanelSearch = {};
  if (panel) result.panel = panel;
  if (stab) result.stab = stab;
  if (side) result.side = side;
  return result;
}

export const NAV_PANEL_SEARCH_KEYS = ["panel", "stab", "side"] as const;
