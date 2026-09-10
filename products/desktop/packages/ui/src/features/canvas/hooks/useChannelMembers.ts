import type { UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export const channelMembersQueryKey = (channelId: string | null) =>
  ["channel-members", channelId] as const;

/** The members of a private channel. Disabled until a channel id is known. */
export function useChannelMembers(channelId: string | null): {
  members: UserBasic[];
  isLoading: boolean;
  error: Error | null;
} {
  const query = useAuthenticatedQuery<UserBasic[]>(
    channelMembersQueryKey(channelId),
    (client) => client.listTaskChannelMembers(channelId as string),
    { enabled: !!channelId },
  );
  return {
    members: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error,
  };
}

/**
 * Replace a private channel's member set. Invalidates both the members query and
 * the channel list, so a space that just became visible or hidden updates too.
 */
export function useSetChannelMembers(channelId: string): {
  setMembers: (userIds: number[]) => Promise<UserBasic[]>;
  isSaving: boolean;
} {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (userIds: number[]) => {
      if (!client) throw new Error("Not authenticated");
      return client.setTaskChannelMembers(channelId, userIds);
    },
    onSuccess: (members) => {
      // The PUT returns the authoritative set, so write it straight in. The channel
      // list still needs a refetch: a space may have just become visible or hidden.
      queryClient.setQueryData<UserBasic[]>(
        channelMembersQueryKey(channelId),
        members,
      );
      void queryClient.invalidateQueries({ queryKey: TASK_CHANNELS_QUERY_KEY });
    },
  });

  return {
    setMembers: (userIds: number[]) => mutation.mutateAsync(userIds),
    isSaving: mutation.isPending,
  };
}
