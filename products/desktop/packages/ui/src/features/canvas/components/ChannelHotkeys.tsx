import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useStarredChannelSlots } from "@posthog/ui/features/canvas/hooks/useStarredChannelSlots";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { navigateToChannel } from "@posthog/ui/router/navigationBridge";
import { track } from "@posthog/ui/shell/analytics";
import { useHotkeys } from "react-hotkeys-hook";

/**
 * Renders nothing — the unconditional owner of ⌘1-9 (switch channel) under the
 * channels layout.
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
      navigateToChannel(channel.id);
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "open_channel",
        surface: "sidebar",
        channel_id: channel.id,
      });
    },
    {
      enabled: channelsLayout,
      enableOnFormTags: true,
      enableOnContentEditable: true,
      preventDefault: true,
    },
    [slots, setCurrentChannel],
  );

  return null;
}
