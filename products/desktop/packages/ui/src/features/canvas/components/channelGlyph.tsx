import {
  HashIcon,
  type IconWeight,
  LockSimpleIcon,
} from "@phosphor-icons/react";
import {
  normalizeChannelName,
  PERSONAL_CHANNEL_NAME,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import type { ReactNode } from "react";

/**
 * Whether only its own members can see a channel.
 *
 * The personal "#me" channel is the only one today — it is per-user and can't
 * be shared. Neither the folder `Channel` nor the backend `TaskChannel` carries
 * a general privacy flag, so this is the one place that has to learn about it
 * when one lands.
 */
export function isPrivateChannel(channelName: string | undefined): boolean {
  if (!channelName) return false;
  return normalizeChannelName(channelName) === PERSONAL_CHANNEL_NAME;
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
  },
): ReactNode {
  if (!isPrivateChannel(channelName) && opts?.space) return null;
  const Icon = isPrivateChannel(channelName) ? LockSimpleIcon : HashIcon;
  return (
    <Icon
      size={opts?.size ?? 16}
      weight={opts?.weight}
      className={opts?.className}
    />
  );
}
