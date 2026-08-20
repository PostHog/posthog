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
 * Keyed on the channel rather than consumed on first read so it survives a
 * re-run of the same route effect (React StrictMode double-invokes mount
 * effects) and expires on its own once the route moves to another channel.
 */
let keepListForChannelId: string | null = null;

export function keepListForRoute(channelId: string): void {
  keepListForChannelId = channelId;
}

export function shouldKeepListForRoute(channelId: string): boolean {
  if (keepListForChannelId === channelId) return true;
  keepListForChannelId = null;
  return false;
}

export function clearKeepListForRoute(): void {
  keepListForChannelId = null;
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
