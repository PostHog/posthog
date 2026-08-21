import { create } from "zustand";

/**
 * Which destination the nav rail has selected, and therefore what the sidebar
 * column beside it shows.
 *
 * Only the destinations that own a sidebar list live here. The rail's other
 * entries (Inbox, Command Center, Loops, Settings) are main-pane destinations
 * with nothing to put in the column, so they route and leave the pane alone.
 */
export type NavRailPane = "channels" | "activity";

interface NavRailState {
  pane: NavRailPane;
  setPane: (pane: NavRailPane) => void;
}

export const useNavRailStore = create<NavRailState>()((set) => ({
  pane: "channels",
  setPane: (pane) => set({ pane }),
}));

/** Put the channel tree back in the column — every channel entry point calls this. */
export function showChannelsRailPane(): void {
  useNavRailStore.getState().setPane("channels");
}

export function showActivityRailPane(): void {
  useNavRailStore.getState().setPane("activity");
}
