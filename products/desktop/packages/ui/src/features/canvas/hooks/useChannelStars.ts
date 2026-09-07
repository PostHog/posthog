import type { TaskChannel } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

/**
 * The current user's starred channels, from the per-user `starred` flag on the
 * channel list. Returns the set of starred channel ids so callers can check
 * whether a channel is starred without re-deriving it from the list.
 */
export function useChannelStars(options?: { enabled?: boolean }): {
  starredChannelIds: ReadonlySet<string>;
  isLoading: boolean;
} {
  const { channels, isLoading } = useChannels(options);
  const starredChannelIds = useMemo(
    () => new Set(channels.filter((c) => c.starred).map((c) => c.id)),
    [channels],
  );
  return { starredChannelIds, isLoading };
}

/**
 * Star/unstar a channel. Flips the flag in the shared channels cache
 * immediately so the sidebar re-sorts the instant the request resolves,
 * rather than waiting on the poll.
 */
export function useChannelStarMutations() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  const setStarredMutation = useMutation({
    mutationFn: async (input: { channelId: string; starred: boolean }) => {
      if (!client) throw new Error("Not authenticated");
      await client.starTaskChannel(input.channelId, input.starred);
      return input;
    },
    // Optimistic update: apply the click the moment it's made and roll back on
    // error. Writing here (not onSuccess) means the last CLICK wins, not the
    // last request to resolve — two rapid toggles resolving out of order can't
    // revert the sidebar to the earlier intent.
    onMutate: async ({ channelId, starred }) => {
      await queryClient.cancelQueries({ queryKey: TASK_CHANNELS_QUERY_KEY });
      const previous = queryClient.getQueryData<TaskChannel[]>(
        TASK_CHANNELS_QUERY_KEY,
      );
      queryClient.setQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY, (old) =>
        old?.map((c) => (c.id === channelId ? { ...c, starred } : c)),
      );
      return { previous };
    },
    onError: (_error, _input, context) => {
      queryClient.setQueryData(TASK_CHANNELS_QUERY_KEY, context?.previous);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: TASK_CHANNELS_QUERY_KEY });
    },
  });

  // Stable identities: a space row's actions are memoized on `toggleStar`,
  // which is built from these — fresh closures here would rebuild that list on
  // every render and write the row's hover-card payload to the card's store
  // with it.
  const { mutateAsync } = setStarredMutation;
  const star = useCallback(
    (channelId: string) => mutateAsync({ channelId, starred: true }),
    [mutateAsync],
  );
  const unstar = useCallback(
    (channelId: string) => mutateAsync({ channelId, starred: false }),
    [mutateAsync],
  );

  return { star, unstar, isUpdating: setStarredMutation.isPending };
}

/**
 * Per-channel star state plus the toggle a channel row needs. Wraps the shared
 * channels query and mutations so the row components stay declarative.
 */
export function useChannelStarToggle(channel: Channel): {
  isStarred: boolean;
  toggleStar: () => void;
} {
  const { star, unstar } = useChannelStarMutations();
  const isStarred = channel.starred;

  const toggleStar = useCallback(() => {
    const run = isStarred ? unstar(channel.id) : star(channel.id);
    run.catch((error: unknown) => {
      toast.error(
        isStarred ? "Couldn't unstar channel" : "Couldn't star channel",
        {
          description: error instanceof Error ? error.message : String(error),
        },
      );
    });
  }, [channel.id, isStarred, star, unstar]);

  return { isStarred, toggleStar };
}
