import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useSpacesTabs } from "@posthog/ui/features/browser-tabs/useSpacesTabs";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import {
  showChannelList,
  showChannelPane,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { requestSidebarSearchFocus } from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { navigateToChannel } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useHotkeys } from "react-hotkeys-hook";

/**
 * Renders nothing — the owner of ⌘1-9 (switch channel) under the channels
 * layout, wherever the tab strip is not. With tabs on, those keys switch tabs
 * (the browser meaning) and this yields them, so a press has one owner.
 *
 * Mounted from the root rather than from the sidebar: the sidebar only renders
 * its channel pane once a channel is already scoped, so binding there left the
 * keys with no owner exactly when the user most needs them (channel list still
 * loading, or failed).
 * GlobalEventHandlers yields SWITCH_TASK to this whenever the layout is on, so
 * there must always be someone listening.
 */
export function ChannelHotkeys() {
  const channelsLayout = useChannelsLayout();
  const spacesTabs = useSpacesTabs();
  const { slots } = useStarredChannelSlots();
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);

  useHotkeys(
    SHORTCUTS.SWITCH_STARRED_CHANNEL,
    (event, handler) => {
      // Same ctrl guard as SWITCH_TASK: plain ctrl+N is the editor-panel tab
      // switcher (SWITCH_TAB), so leave ctrl-only presses to it.
      if (event.ctrlKey && !event.metaKey) return;
      const slot = Number.parseInt(handler.keys?.[0] ?? "", 10);
      if (Number.isNaN(slot)) return;
      const channel = slots[slot - 1];
      if (!channel) return;
      setCurrentChannel(channel.id);
      // Said outright rather than left to the route effect: this key is a
      // request to be in the space, and the effect skips the slide for a
      // navigation the list asked to stay out of.
      showChannelPane();
      navigateToChannel(channel.id);
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "open_channel",
        surface: "sidebar",
        channel_id: channel.id,
      });
    },
    {
      enabled: channelsLayout && !spacesTabs,
      enableOnFormTags: true,
      enableOnContentEditable: true,
      preventDefault: true,
    },
    [slots, setCurrentChannel],
  );

  // Jump to the space list from anywhere: open the sidebar if it's collapsed,
  // slide it back to the list, and hand the keyboard to the search box, which
  // is also the tree's keyboard driver.
  useHotkeys(
    SHORTCUTS.FOCUS_SIDEBAR_SEARCH,
    () => {
      useSidebarStore.getState().setOpen(true);
      showChannelList();
      requestSidebarSearchFocus();
    },
    {
      enabled: channelsLayout,
      enableOnFormTags: true,
      enableOnContentEditable: true,
      preventDefault: true,
    },
    [],
  );

  return null;
}
