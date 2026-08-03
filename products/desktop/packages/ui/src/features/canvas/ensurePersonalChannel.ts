import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";

/**
 * The user's private "#me" channel from the channels list. Personal channels
 * are provisioned lazily server-side when the channel list is fetched, so
 * there is nothing to create client-side — `undefined` just means the list
 * hasn't loaded (or provisioned) it yet.
 */
export function ensurePersonalChannel(
  channels: readonly Channel[],
): Channel | undefined {
  return channels.find((c) => c.channelType === "personal");
}
