import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
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
  animateTransition: boolean;
  setPane: (pane: ChannelPane, animateTransition?: boolean) => void;
  finishTransition: () => void;
}

export const useChannelPaneStore = create<ChannelPaneState>()((set) => ({
  // A scoped channel is the resting state, so a cold start lands on the channel
  // rather than sliding away from it.
  pane: "channel",
  animateTransition: false,
  setPane: (pane, animateTransition = false) =>
    set({ pane, animateTransition }),
  finishTransition: () => set({ animateTransition: false }),
}));

interface ShowChannelListOptions {
  keepForRoute?: string;
  animate?: boolean;
}

interface ShowChannelPaneOptions {
  animate?: boolean;
}

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

/**
 * Slide back to the channel list, keeping the scoped channel as it is.
 *
 * Pass `keepForRoute` when the caller is about to navigate into that channel:
 * arriving at a channel pulls the slider to it, and the latch holds the list
 * across that navigation.
 */
export function showChannelList({
  keepForRoute,
  animate = false,
}: ShowChannelListOptions = {}): void {
  keepListForChannelId = keepForRoute ?? null;
  useChannelPaneStore.getState().setPane("list", animate);
}

/** Slide to the channel pane — every channel entry point goes through here. */
export function showChannelPane({
  animate = false,
}: ShowChannelPaneOptions = {}): void {
  keepListForChannelId = null;
  useChannelPaneStore.getState().setPane("channel", animate);
}

/**
 * Put the sidebar back the way a tab left it.
 *
 * The pane and the scoped space are window-global stores, but each tab has its
 * own. Switching tabs has to restore them, or the next navigation effect reads
 * the tab you *left* and writes that over the tab you arrived at.
 *
 * `showChannelList` arms the keep-list latch, so an in-flight navigation into
 * the space does not immediately slide the list away again.
 */
export function applyTabViewState(view: {
  listOpen?: boolean;
  spaceId?: string | null;
}): void {
  useChannelPaneStore.getState().finishTransition();
  // A stored null explicitly clears the space; only an absent value is skipped.
  if (view.spaceId !== undefined) {
    useCurrentChannelStore.getState().setCurrentChannel(view.spaceId);
  }
  if (view.listOpen === undefined) return;
  if (view.listOpen) {
    showChannelList({ keepForRoute: view.spaceId ?? undefined });
  } else showChannelPane();
}
