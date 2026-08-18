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

/**
 * Set by a navigation that is not a request to enter the space it belongs to:
 * opening a session from the list's tree, or the first-run landing on #general.
 * The route effect that otherwise slides into the space checks it.
 *
 * Keyed on the channel rather than consumed on first read so it survives a
 * re-run of the same route effect (React StrictMode double-invokes mount
 * effects) and expires on its own once the route moves to another channel.
 * Any explicit pane change below drops it.
 */
let keepListForChannelId: string | null = null;

/** Keep the sidebar on the list while the route lands on this channel. */
export function keepListForRoute(channelId: string): void {
  keepListForChannelId = channelId;
}

/** True while the route effect is landing on the kept channel; clears once it isn't. */
export function shouldKeepListForRoute(channelId: string): boolean {
  if (keepListForChannelId === channelId) return true;
  keepListForChannelId = null;
  return false;
}

/** Slide back to the channel list, keeping the scoped channel as it is. */
export function showChannelList(): void {
  keepListForChannelId = null;
  useChannelPaneStore.getState().setPane("list");
}

/** Slide to the channel pane — every channel entry point goes through here. */
export function showChannelPane(): void {
  keepListForChannelId = null;
  useChannelPaneStore.getState().setPane("channel");
}
