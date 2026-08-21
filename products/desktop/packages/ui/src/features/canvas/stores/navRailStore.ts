import { create } from "zustand";

/**
 * Which rail destination is selected, and therefore what the column beside the
 * rail shows.
 *
 * Only two destinations own that column: Spaces draws the channel tree (and the
 * channel you slide into from it), Activity draws the feed. The rest are
 * whole-screen destinations with no list of their own, so the column collapses
 * away and the content pane takes its width.
 */
export type NavRailPane =
  | "home"
  | "spaces"
  | "activity"
  | "inbox"
  | "command-center"
  | "loops";

const PANES_WITH_SIDEBAR = new Set<NavRailPane>(["spaces", "activity"]);

export function railPaneHasSidebar(pane: NavRailPane): boolean {
  return PANES_WITH_SIDEBAR.has(pane);
}

interface NavRailState {
  pane: NavRailPane;
  setPane: (pane: NavRailPane) => void;
}

export const useNavRailStore = create<NavRailState>()((set) => ({
  pane: "spaces",
  setPane: (pane) => set({ pane }),
}));

/** Put the channel tree back in the column — every channel entry point calls this. */
export function showSpacesRailPane(): void {
  useNavRailStore.getState().setPane("spaces");
}
