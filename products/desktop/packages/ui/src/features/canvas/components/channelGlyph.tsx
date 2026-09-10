import {
  HashIcon,
  type IconWeight,
  LockSimpleIcon,
} from "@phosphor-icons/react";
import { PERSONAL_CHANNEL_LABEL } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import type { ReactNode } from "react";

/**
 * Whether a name reads as the viewer's own "#me" space, judged by the name.
 *
 * This is a fallback for surfaces that hold a name and nothing else. A caller
 * with the channel in hand must pass `personal` to avoid deciding it from a
 * display label.
 */
export function isPersonalChannelName(
  channelName: string | undefined,
): boolean {
  if (!channelName) return false;
  return channelName.trim().toLowerCase() === PERSONAL_CHANNEL_LABEL;
}

/**
 * A channel's leading glyph: the viewer's own "#me" space wears a plain lock, a
 * private shared space the same lock, the legacy Channels layout a hash, and an
 * ordinary space nothing at all.
 *
 * Spaces dropped their cube because it said nothing the name didn't — a column
 * of identical marks is noise, and the only thing worth calling out in that list
 * is a space not everyone can see. The hash stays where it still separates a
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
     * Whether this is the viewer's own "#me" space. Pass it wherever the channel
     * is in hand: the lock says "only you can see this", and deciding that from
     * a name hands it to any public space that took the name.
     */
    personal?: boolean;
    /**
     * Whether this is a private shared space with access limited to members.
     */
    private?: boolean;
  },
): ReactNode {
  const personal = opts?.personal ?? isPersonalChannelName(channelName);
  const isPrivate = opts?.private ?? false;
  if (!personal && !isPrivate && opts?.space) return null;
  const Icon = personal || isPrivate ? LockSimpleIcon : HashIcon;
  return (
    <Icon
      size={opts?.size ?? 16}
      weight={opts?.weight}
      className={opts?.className}
    />
  );
}
