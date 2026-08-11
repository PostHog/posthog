import { create } from "zustand";

/**
 * The chrome's panel state: which secondary panel is showing, which list it's
 * on, and which right panel is open.
 *
 * This is view state, not navigation. It lived in root-level search params for
 * a while, which made it shareable but made every toggle a router navigation —
 * and a root-level search change re-renders every matched route, so a tab click
 * cost 250ms on a space and over a second on Home. A store updates only the
 * components that read it.
 */

/** Tab inside a space's secondary panel. */
export type SpacePanelTab = "sessions" | "loops" | "canvases";

/** Which right panel is open. `changes` also opens via reviewNavigationStore. */
export type RightPanelSide = "artifacts" | "comments" | "changes";

/**
 * "auto" follows the route (a space route shows that space's panel), "activity"
 * pins the activity feed whatever the route, "off" closes it.
 */
export type SecondaryPanelMode = "auto" | "activity" | "off";

interface NavPanelStore {
  panel: SecondaryPanelMode;
  stab: SpacePanelTab;
  side: RightPanelSide | null;
  setPanel: (panel: SecondaryPanelMode) => void;
  setStab: (stab: SpacePanelTab) => void;
  setSide: (side: RightPanelSide | null) => void;
  /** Back to defaults, for a move to a destination that should open fresh. */
  reset: () => void;
}

const DEFAULTS = {
  panel: "auto",
  stab: "sessions",
  side: null,
} as const satisfies Pick<NavPanelStore, "panel" | "stab" | "side">;

export const useNavPanelStore = create<NavPanelStore>()((set) => ({
  ...DEFAULTS,
  setPanel: (panel) => set({ panel }),
  setStab: (stab) => set({ stab }),
  setSide: (side) => set({ side }),
  reset: () => set({ ...DEFAULTS }),
}));
