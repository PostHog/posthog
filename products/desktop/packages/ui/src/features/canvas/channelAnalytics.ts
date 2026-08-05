import { resolveServiceOptional } from "@posthog/di/container";
import {
  ANALYTICS_EVENTS,
  type ChannelActionProperties,
} from "@posthog/shared/analytics-events";
import type { TaskChannel } from "@posthog/shared/domain-types";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { track } from "@posthog/ui/shell/analytics";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";

/**
 * Every Channel action is captured through here so channel_type is stamped
 * even at sites that only hold a channel_id — resolved from the cached
 * channels list rather than threaded through each call site. An explicit
 * channel_type from the caller wins over the cache.
 */
export function trackChannelAction(properties: ChannelActionProperties): void {
  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
    ...properties,
    channel_type:
      properties.channel_type ?? lookupChannelType(properties.channel_id),
  });
}

function lookupChannelType(
  channelId: string | undefined,
): ChannelActionProperties["channel_type"] {
  if (!channelId) return undefined;
  return resolveServiceOptional<ImperativeQueryClient>(IMPERATIVE_QUERY_CLIENT)
    ?.getQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY)
    ?.find((channel) => channel.id === channelId)?.channel_type;
}
