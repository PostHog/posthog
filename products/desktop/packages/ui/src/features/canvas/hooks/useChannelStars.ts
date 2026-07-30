import type { Schemas } from "@posthog/api-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const STARS_POLL_INTERVAL_MS = 60_000;
const STARS_QUERY_KEY = ["canvas-channel-stars"] as const;

// Channels are folders, so their stars are folder-typed shortcuts. Anything
// else on the desktop surface (a starred insight, say) is ignored here.
const FOLDER_SHORTCUT_TYPE = "folder";

/**
 * The current user's starred channels, persisted in the PostHog backend as
 * per-user desktop file-system shortcuts. Returns a map from a channel's raw
 * path (the shortcut `ref`) to the shortcut id, so callers can both check
 * whether a channel is starred and delete the right shortcut when unstarring.
 */
export function useChannelStars(options?: { enabled?: boolean }): {
  starredRefToShortcutId: Map<string, string>;
  isLoading: boolean;
} {
  const query = useAuthenticatedQuery<Schemas.FileSystemShortcut[]>(
    STARS_QUERY_KEY,
    (client) => client.getDesktopFileSystemShortcuts(),
    {
      enabled: options?.enabled ?? true,
      refetchInterval: STARS_POLL_INTERVAL_MS,
    },
  );

  const starredRefToShortcutId = new Map<string, string>();
  for (const shortcut of query.data ?? []) {
    if (shortcut.type === FOLDER_SHORTCUT_TYPE && shortcut.ref) {
      starredRefToShortcutId.set(shortcut.ref, shortcut.id);
    }
  }

  return { starredRefToShortcutId, isLoading: query.isLoading };
}

/**
 * Star/unstar a channel by creating or deleting its desktop shortcut. Both
 * paths update the shared shortcuts cache immediately so the sidebar re-sorts
 * the instant the request resolves, rather than waiting on the poll.
 */
export function useChannelStarMutations() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: STARS_QUERY_KEY });
  }, [queryClient]);

  const starMutation = useMutation({
    mutationFn: async (channel: Channel) => {
      if (!client) throw new Error("Not authenticated");
      return client.createDesktopFileSystemShortcut({
        path: channel.name,
        type: FOLDER_SHORTCUT_TYPE,
        ref: channel.path,
      });
    },
    onSuccess: (created) => {
      queryClient.setQueryData<Schemas.FileSystemShortcut[]>(
        STARS_QUERY_KEY,
        (old) => {
          if (!old) return [created];
          if (old.some((s) => s.id === created.id)) return old;
          return [...old, created];
        },
      );
      invalidate();
    },
  });

  const unstarMutation = useMutation({
    mutationFn: async (shortcutId: string) => {
      if (!client) throw new Error("Not authenticated");
      await client.deleteDesktopFileSystemShortcut(shortcutId);
      return shortcutId;
    },
    onSuccess: (shortcutId) => {
      queryClient.setQueryData<Schemas.FileSystemShortcut[]>(
        STARS_QUERY_KEY,
        (old) => (old ?? []).filter((s) => s.id !== shortcutId),
      );
      invalidate();
    },
  });

  return {
    star: (channel: Channel) => starMutation.mutateAsync(channel),
    unstar: (shortcutId: string) => unstarMutation.mutateAsync(shortcutId),
    isStarring: starMutation.isPending,
    isUnstarring: unstarMutation.isPending,
  };
}

/**
 * Per-channel star state plus the actions a channel row needs. Wraps the shared
 * stars query and mutations so the row components stay declarative. Multiple
 * rows calling this share one underlying query (React Query dedupes by key).
 */
export function useChannelStarToggle(channel: Channel): {
  isStarred: boolean;
  toggleStar: () => void;
  /** Remove the star if present — used when the channel itself is deleted so
   *  a same-named channel created later doesn't inherit a stale star. */
  removeStar: () => void;
} {
  const { starredRefToShortcutId } = useChannelStars();
  const { star, unstar } = useChannelStarMutations();
  const shortcutId = starredRefToShortcutId.get(channel.path);
  const isStarred = shortcutId !== undefined;

  const toggleStar = useCallback(() => {
    const run = shortcutId ? unstar(shortcutId) : star(channel);
    run.catch((error: unknown) => {
      toast.error(
        isStarred ? "Couldn't unstar channel" : "Couldn't star channel",
        {
          description: error instanceof Error ? error.message : String(error),
        },
      );
    });
  }, [channel, shortcutId, isStarred, star, unstar]);

  const removeStar = useCallback(() => {
    if (shortcutId) {
      void unstar(shortcutId);
    }
  }, [shortcutId, unstar]);

  return { isStarred, toggleStar, removeStar };
}
