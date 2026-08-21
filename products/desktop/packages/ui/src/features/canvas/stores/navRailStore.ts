import { create } from "zustand";

/**
 * Which rail destination is selected. Only Spaces and Activity own the column
 * beside the rail; the rest are whole-screen and collapse it away.
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
