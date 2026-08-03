import { useChannelStars } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { PERSONAL_CHANNEL_NAME } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useMemo } from "react";

export const STARRED_HOTKEY_SLOTS = 9;

export function useStarredChannelSlots(): {
  slots: Channel[];
  rest: Channel[];
  slotFor: (channel: Channel) => number | undefined;
} {
  const { channels } = useChannels();
  const { starredRefToShortcutId } = useChannelStars();

  return useMemo(() => {
    const me = channels.find((c) => c.name === PERSONAL_CHANNEL_NAME) ?? null;
    const byPath = new Map(channels.map((c) => [c.path, c]));
    const starred: Channel[] = [];
    for (const ref of starredRefToShortcutId.keys()) {
      const channel = byPath.get(ref);
      if (channel && channel.name !== PERSONAL_CHANNEL_NAME) {
        starred.push(channel);
      }
    }
    const slots = (me ? [me, ...starred] : starred).slice(
      0,
      STARRED_HOTKEY_SLOTS,
    );
    const slotted = new Set(slots.map((c) => c.id));
    const rest = channels
      .filter((c) => !slotted.has(c.id))
      .sort((a, b) => a.name.localeCompare(b.name));
    const slotIndex = new Map(slots.map((c, index) => [c.id, index + 1]));
    return {
      slots,
      rest,
      slotFor: (channel: Channel) => slotIndex.get(channel.id),
    };
  }, [channels, starredRefToShortcutId]);
}
