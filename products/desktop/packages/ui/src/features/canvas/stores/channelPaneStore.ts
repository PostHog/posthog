import { create } from "zustand";

/**
 * Which of the two sidebar panes the Channels layout is showing.
 *
 * The sidebar is a master/detail slider: the channel list, and the channel you
 * are in. Which one shows is view state, not a route — going "back to channels"
 * browses the list while you stay in the channel, so the scoped channel
 * (`currentChannelStore`) and the visible pane have to be separate facts.
 */
type ChannelPane = "list" | "channel";

interface ChannelPaneState {
  pane: ChannelPane;
  setPane: (pane: ChannelPane) => void;
}

export const useChannelPaneStore = create<ChannelPaneState>()((set) => ({
  // A scoped channel is the resting state, so a cold start lands on the channel
  // rather than sliding away from it.
  pane: "channel",
  setPane: (pane) => set({ pane }),
}));

/** Slide back to the channel list, keeping the scoped channel as it is. */
export function showChannelList(): void {
  useChannelPaneStore.getState().setPane("list");
}

/** Slide to the channel pane — every channel entry point goes through here. */
export function showChannelPane(): void {
  useChannelPaneStore.getState().setPane("channel");
}
