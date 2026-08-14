import type { TaskChannel, UserBasic } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  TASK_CHANNELS_QUERY_KEY,
  useTaskChannels,
} from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

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
  /** The repos the space is wired to. Empty where none are. */
  repositories: string[];
  /** Who made the space, where the backend knows. */
  createdBy: UserBasic | null;
}

const NO_REPOSITORIES: string[] = [];

function toChannel(channel: TaskChannel): Channel {
  return {
    id: channel.id,
    name: channel.name,
    channelType: channel.channel_type,
    starred: channel.starred,
    repositories: channel.repositories ?? NO_REPOSITORIES,
    createdBy: channel.created_by ?? null,
  };
}

/**
 * List the project's channels, normalized for the Home-space UI. A thin view
 * over `useTaskChannels` — the single task-channels query (one key, one poll
 * cadence) — so star and create mutations keep one cache coherent.
 */
export function useChannels(options?: { enabled?: boolean }): {
  channels: Channel[];
  isLoading: boolean;
} {
  const { channels: taskChannels, isLoading } = useTaskChannels(options);
  // Memoize so the array reference is stable while the underlying data is
  // unchanged — callers depend on `channels` in their own memos/effects.
  const channels = useMemo(
    () =>
      taskChannels.map(toChannel).sort((a, b) => a.name.localeCompare(b.name)),
    [taskChannels],
  );
  return { channels, isLoading };
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
    mutationFn: async ({ name, star }: { name: string; star: boolean }) => {
      if (!client) throw new Error("Not authenticated");
      // Resolve-or-create is idempotent server-side, so racing creators of the
      // same name converge on one channel.
      // Names that reach here are already lowercase-dashed (the create form
      // rejects anything else), so they match server-normalized names as typed.
      // An unfetched list reads as undefined rather than "no such name", and
      // starring a space the user had unstarred is worse than not starring a
      // new one, so only a loaded list without the name earns the fallback.
      const isNewToTheList = queryClient
        .getQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY)
        ?.every((channel) => channel.name !== name);
      const created = await client.resolveTaskChannel(name, { star });
      if (!star || created.starred || !isNewToTheList) return created;
      // TODO: delete once `star` on create is live on Cloud. A backend that
      // predates it drops the flag and hands back an unstarred channel, so ask
      // again through the star endpoint every version has. Resolving a channel
      // that already existed is left alone either way — its star is the user's.
      try {
        await client.starTaskChannel(created.id, true);
        return { ...created, starred: true };
      } catch {
        // The space exists either way, and the star is one click to fix, so a
        // failure here isn't worth failing the create the user asked for.
        return created;
      }
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
    createChannel: (name: string, options: { star: boolean }) =>
      createMutation.mutateAsync({ name, star: options.star }).then(toChannel),
    deleteChannel: (id: string) => deleteMutation.mutateAsync(id),
    renameChannel: (id: string, name: string) =>
      renameMutation.mutateAsync({ id, name }).then(toChannel),
    isCreating: createMutation.isPending,
    isDeleting: deleteMutation.isPending,
    isRenaming: renameMutation.isPending,
  };
}
