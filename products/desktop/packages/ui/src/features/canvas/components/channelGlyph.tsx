import {
  HashIcon,
  type IconWeight,
  LockSimpleIcon,
} from "@phosphor-icons/react";
import { PERSONAL_CHANNEL_LABEL } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import type { ReactNode } from "react";

/**
 * Whether only its own members can see a channel, judged by its name.
 *
 * This is a fallback for surfaces that hold a name and nothing else. A caller
 * with the channel in hand must pass `personal` to avoid deciding privacy from
 * a display label.
 */
export function isPrivateChannel(channelName: string | undefined): boolean {
  if (!channelName) return false;
  return channelName.trim().toLowerCase() === PERSONAL_CHANNEL_LABEL;
}

/**
 * A channel's leading glyph: a lock when it's private, a hash under the legacy
 * Channels layout, and nothing at all for a space.
 *
 * Spaces dropped their cube because it said nothing the name didn't — a column
 * of identical marks is noise, and the only thing worth calling out in that list
 * is the one space that isn't shared. The hash stays where it still separates a
 * channel from the other things in that tree.
 */
export function channelGlyph(
  channelName: string | undefined,
  opts?: {
    size?: number;
    className?: string;
    weight?: IconWeight;
    space?: boolean;
    /**
     * Whether this is the viewer's private space. Pass it wherever the channel
     * is in hand: the lock says "only you can see this", and deciding that from
     * a name hands it to any public space that took the name.
     */
    personal?: boolean;
  },
): ReactNode {
  const personal = opts?.personal ?? isPrivateChannel(channelName);
  if (!personal && opts?.space) return null;
  const Icon = personal ? LockSimpleIcon : HashIcon;
  return (
    <Icon
      size={opts?.size ?? 16}
      weight={opts?.weight}
      className={opts?.className}
    />
  );
}
