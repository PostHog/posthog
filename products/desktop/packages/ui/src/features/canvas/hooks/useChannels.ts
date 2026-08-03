import type { TaskChannel } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

const CHANNELS_POLL_INTERVAL_MS = 30_000;

/** A Home-space channel: a backend task channel (one UUID for everything). */
export interface Channel {
  /** Backend task channel UUID. */
  id: string;
  /** Normalized display name (lowercase-dashed; rendered "#name"). */
  name: string;
  /** `personal` is the user's private "#me" channel. */
  channelType: "public" | "personal";
  /** Whether the current user starred this channel. */
  starred: boolean;
}

function toChannel(channel: TaskChannel): Channel {
  return {
    id: channel.id,
    name: channel.name,
    channelType: channel.channel_type,
    starred: channel.starred,
  };
}

/**
 * List the project's channels. Shares the task-channels query key so star and
 * create mutations keep one cache coherent.
 */
export function useChannels(options?: { enabled?: boolean }): {
  channels: Channel[];
  isLoading: boolean;
} {
  const query = useAuthenticatedQuery<TaskChannel[]>(
    TASK_CHANNELS_QUERY_KEY,
    (client) => client.getTaskChannels(),
    {
      enabled: options?.enabled ?? true,
      refetchInterval: CHANNELS_POLL_INTERVAL_MS,
    },
  );
  // Memoize so the array reference is stable while the underlying data is
  // unchanged — callers depend on `channels` in their own memos/effects.
  const channels = useMemo(
    () =>
      (query.data ?? [])
        .map(toChannel)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [query.data],
  );
  return { channels, isLoading: query.isLoading };
}

/**
 * Create/rename/delete channels. All invalidate the shared query key so the
 * list refetches immediately rather than waiting on the poll.
 */
export function useChannelMutations() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: TASK_CHANNELS_QUERY_KEY });
  }, [queryClient]);

  const createMutation = useMutation({
    mutationFn: async (name: string) => {
      if (!client) throw new Error("Not authenticated");
      // Resolve-or-create is idempotent server-side, so racing creators of the
      // same name converge on one channel.
      return client.resolveTaskChannel(name);
    },
    onSuccess: (created) => {
      // Insert the created channel into the cache immediately so the sidebar
      // updates the instant the POST resolves, rather than waiting on the
      // refetch that `invalidate` triggers.
      queryClient.setQueryData<TaskChannel[]>(
        TASK_CHANNELS_QUERY_KEY,
        (old) => {
          if (!old) return [created];
          if (old.some((c) => c.id === created.id)) return old;
          return [...old, created];
        },
      );
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      if (!client) throw new Error("Not authenticated");
      return client.deleteTaskChannel(id);
    },
    onSuccess: invalidate,
  });

  const renameMutation = useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }) => {
      if (!client) throw new Error("Not authenticated");
      return client.renameTaskChannel(id, name);
    },
    onSuccess: invalidate,
  });

  return {
    createChannel: (name: string) =>
      createMutation.mutateAsync(name).then(toChannel),
    deleteChannel: (id: string) => deleteMutation.mutateAsync(id),
    renameChannel: (id: string, name: string) =>
      renameMutation.mutateAsync({ id, name }).then(toChannel),
    isCreating: createMutation.isPending,
    isDeleting: deleteMutation.isPending,
    isRenaming: renameMutation.isPending,
  };
}
