import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useMemo } from "react";

export const STARRED_HOTKEY_SLOTS = 9;

export function useStarredChannelSlots(): {
  slots: Channel[];
  rest: Channel[];
  slotFor: (channel: Channel) => number | undefined;
} {
  const { channels } = useChannels();

  return useMemo(() => {
    const me = channels.find((c) => c.channelType === "personal") ?? null;
    const starred = channels.filter(
      (c) => c.channelType !== "personal" && c.starred,
    );
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
  }, [channels]);
}
