/**
 * The chrome's panel state, carried in the URL so any exact view is shareable
 * and restorable. Widths stay in persisted stores — they'd churn the URL on
 * every drag.
 *
 * Every param always has a value, including its default. Absence would be the
 * tidier encoding, but `retainSearchParams` (see __root) can't tell a key a
 * navigation deleted from one it never mentioned, so it restores the old value
 * and the panel can never be returned to its default. An explicit default is
 * visible to it; `stripSearchParams` then keeps it out of the URL.
 */

/** Tab inside a space's secondary panel. */
export type SpacePanelTab = "sessions" | "loops" | "canvases";

/** Which right panel is open. `changes` also opens via reviewNavigationStore. */
export type RightPanelSide = "artifacts" | "comments" | "changes";

/**
 * `panel` selects the secondary panel: "auto" follows the route (a space route
 * shows that space's panel), "activity" pins the activity feed regardless of
 * route, "off" closes it for the current destination.
 */
export type SecondaryPanelParam = "auto" | "activity" | "off";

/** `side` is the right panel, with "none" standing for closed. */
export type RightPanelParam = RightPanelSide | "none";

export interface NavPanelSearch {
  panel: SecondaryPanelParam;
  stab: SpacePanelTab;
  side: RightPanelParam;
}

export const NAV_PANEL_DEFAULTS: NavPanelSearch = {
  panel: "auto",
  stab: "sessions",
  side: "none",
};

const PANEL_VALUES: readonly SecondaryPanelParam[] = [
  "auto",
  "activity",
  "off",
];
const SPACE_TAB_VALUES: readonly SpacePanelTab[] = [
  "sessions",
  "loops",
  "canvases",
];
const SIDE_VALUES: readonly RightPanelParam[] = [
  "artifacts",
  "comments",
  "changes",
  "none",
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
export function resolveNavPanelSearch(
  search: Record<string, unknown>,
): NavPanelSearch {
  return {
    panel: oneOf(search.panel, PANEL_VALUES) ?? NAV_PANEL_DEFAULTS.panel,
    stab: oneOf(search.stab, SPACE_TAB_VALUES) ?? NAV_PANEL_DEFAULTS.stab,
    side: oneOf(search.side, SIDE_VALUES) ?? NAV_PANEL_DEFAULTS.side,
  };
}

/**
 * The route-level validator. Every value is concrete at runtime, but the type
 * is partial on purpose: a required search param would make `search` mandatory
 * on every `navigate`/`redirect` in the app, and the chrome's params are the
 * router's business, not each caller's. Read them through
 * `useNavPanelSearch()`, which resolves the defaults back.
 */
export const validateNavPanelSearch = (
  search: Record<string, unknown>,
): Partial<NavPanelSearch> => resolveNavPanelSearch(search);

export const NAV_PANEL_SEARCH_KEYS = ["panel", "stab", "side"] as const;
