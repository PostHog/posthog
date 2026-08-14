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
 * Set by a navigation that is not a request to enter the space it belongs to —
 * opening a session from the list's tree. The route effect that otherwise
 * slides into the space consumes it.
 *
 * Deliberately not store state: it decides what a single navigation does, and a
 * render pass is the wrong lifetime for that. Any explicit pane change below
 * drops it, so it can't outlive the navigation it was set for.
 */
let keepListOnNextRoute = false;

/** Keep the sidebar on the list through the navigation that follows. */
export function keepListForNextRoute(): void {
  keepListOnNextRoute = true;
}

/** Reads the flag and clears it. */
export function consumeKeepListForNextRoute(): boolean {
  const keep = keepListOnNextRoute;
  keepListOnNextRoute = false;
  return keep;
}

/** Slide back to the channel list, keeping the scoped channel as it is. */
export function showChannelList(): void {
  keepListOnNextRoute = false;
  useChannelPaneStore.getState().setPane("list");
}

/** Slide to the channel pane — every channel entry point goes through here. */
export function showChannelPane(): void {
  keepListOnNextRoute = false;
  useChannelPaneStore.getState().setPane("channel");
}
