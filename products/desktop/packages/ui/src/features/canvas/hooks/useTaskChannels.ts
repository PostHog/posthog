import {
  channelDisplayName,
  isGeneralChannel,
  isPersonalChannel,
} from "@posthog/core/canvas/channelName";
import type { TaskChannel } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

const TASK_CHANNELS_POLL_INTERVAL_MS = 30_000;
export const TASK_CHANNELS_QUERY_KEY = ["task-channels"] as const;

// One definition, in core: an activity row and a mention carry a channel name
// of their own, and neither goes through this hook.
export {
  PERSONAL_CHANNEL_LABEL,
  PERSONAL_CHANNEL_NAME,
} from "@posthog/core/canvas/channelName";

/**
 * Backend task channels. Feed, threads, instructions and canvases all hang off
 * the same channel UUID.
 */
export function useTaskChannels(options?: { enabled?: boolean }): {
  channels: TaskChannel[];
  personalChannel: TaskChannel | undefined;
  generalChannel: TaskChannel | undefined;
  isLoading: boolean;
} {
  const query = useAuthenticatedQuery<TaskChannel[]>(
    TASK_CHANNELS_QUERY_KEY,
    (client) => client.getTaskChannels(),
    {
      enabled: options?.enabled ?? true,
      refetchInterval: TASK_CHANNELS_POLL_INTERVAL_MS,
    },
  );
  const channels = useMemo(
    () =>
      (query.data ?? []).map((channel) =>
        isPersonalChannel(channel)
          ? { ...channel, name: channelDisplayName(channel.name) }
          : channel,
      ),
    [query.data],
  );
  const personalChannel = useMemo(
    () => channels.find((c) => isPersonalChannel(c)),
    [channels],
  );
  const generalChannel = useMemo(
    () => channels.find((c) => isGeneralChannel(c)),
    [channels],
  );
  return {
    channels,
    personalChannel,
    generalChannel,
    isLoading: query.isLoading,
  };
}

export function useUpdateTaskChannelRepositories() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: {
      channelId: string;
      githubIntegration: number | null;
      repositories: string[];
    }) => {
      if (!client) throw new Error("Not authenticated");
      return client.updateTaskChannelRepositories(
        input.channelId,
        input.githubIntegration,
        input.repositories,
      );
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: TASK_CHANNELS_QUERY_KEY });
      const previous = queryClient.getQueryData<TaskChannel[]>(
        TASK_CHANNELS_QUERY_KEY,
      );
      queryClient.setQueryData<TaskChannel[]>(
        TASK_CHANNELS_QUERY_KEY,
        (channels) =>
          channels?.map((channel) =>
            channel.id === input.channelId
              ? {
                  ...channel,
                  github_integration: input.githubIntegration,
                  repositories: input.repositories,
                }
              : channel,
          ),
      );
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) {
        queryClient.setQueryData(TASK_CHANNELS_QUERY_KEY, context.previous);
      }
    },
    onSuccess: (updatedChannel) => {
      queryClient.setQueryData<TaskChannel[]>(
        TASK_CHANNELS_QUERY_KEY,
        (channels) =>
          channels?.map((channel) =>
            channel.id === updatedChannel.id ? updatedChannel : channel,
          ),
      );
    },
  });
}
