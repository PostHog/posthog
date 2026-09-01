import type {
  SlackChannelsQueryParams,
  SlackChannelsResponse,
} from "@posthog/shared/domain-types";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";

const DEFAULT_CHANNEL_PAGE_SIZE = 50;

export interface UseSlackChannelsOptions extends SlackChannelsQueryParams {
  enabled?: boolean;
}

export function useSlackChannels(
  integrationId: number | null | undefined,
  options?: UseSlackChannelsOptions,
) {
  const {
    search,
    limit = DEFAULT_CHANNEL_PAGE_SIZE,
    offset,
    channelId,
    enabled = true,
  } = options ?? {};
  const normalizedSearch = search?.trim() || undefined;

  return useAuthenticatedQuery<SlackChannelsResponse>(
    [
      "slack",
      "channels",
      integrationId ?? null,
      normalizedSearch ?? "",
      limit,
      offset ?? 0,
      channelId ?? null,
    ],
    async (client) => {
      if (!integrationId) {
        return { channels: [] };
      }
      return await client.getSlackChannelsForIntegration(integrationId, {
        search: normalizedSearch,
        limit,
        offset,
        channelId,
      });
    },
    {
      enabled: !!integrationId && enabled,
      refetchOnWindowFocus: false,
      // Full lists are cached server-side for an hour; search pages refresh sooner.
      staleTime: normalizedSearch || channelId ? 30_000 : 5 * 60_000,
    },
  );
}
