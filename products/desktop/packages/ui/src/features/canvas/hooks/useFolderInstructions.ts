import type {
  ChannelInstructions,
  ChannelInstructionsVersion,
} from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const CHANNEL_INSTRUCTIONS_QUERY_KEY = (channelId: string) =>
  ["channel-instructions", channelId] as const;

const CHANNEL_INSTRUCTIONS_VERSIONS_QUERY_KEY = (channelId: string) =>
  ["channel-instructions", channelId, "versions"] as const;

// While a channel has no published CONTEXT.md, `pollWhileEmpty` views refetch
// on this cadence so an agent's mid-run publish (via the MCP) appears without
// a manual reload. Polling stops as soon as content exists.
const CHANNEL_INSTRUCTIONS_EMPTY_POLL_INTERVAL_MS = 5_000;

// Latest published version of the channel's instructions (a channel with none
// reads as blank content at version 0). The latest content is what the editor
// opens with; the editor never edits an old version in-place, it republishes
// from current latest.
export function useFolderInstructions(
  channelId: string | null,
  options?: { enabled?: boolean; pollWhileEmpty?: boolean },
) {
  return useAuthenticatedQuery<ChannelInstructions | null>(
    channelId
      ? CHANNEL_INSTRUCTIONS_QUERY_KEY(channelId)
      : (["channel-instructions", "none"] as const),
    async (client) => {
      if (!channelId) return null;
      return client.getChannelInstructions(channelId);
    },
    {
      enabled: Boolean(channelId) && (options?.enabled ?? true),
      // Always refetch on mount so opening CONTEXT.md after another user (or
      // an agent) edited it from elsewhere shows the current content, not the
      // last-cached body.
      staleTime: 0,
      refetchOnMount: "always",
      refetchInterval: options?.pollWhileEmpty
        ? (query) =>
            (query.state.data?.content ?? "").trim().length > 0
              ? false
              : CHANNEL_INSTRUCTIONS_EMPTY_POLL_INTERVAL_MS
        : undefined,
    },
  );
}

// Newest-first list of version metadata (no content) — used by the version
// dropdown. The list refetches after every publish/delete via the same key
// invalidation in the mutations hook below.
export function useFolderInstructionsVersions(
  channelId: string | null,
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<ChannelInstructionsVersion[]>(
    channelId
      ? CHANNEL_INSTRUCTIONS_VERSIONS_QUERY_KEY(channelId)
      : (["channel-instructions", "none", "versions"] as const),
    async (client) => {
      if (!channelId) return [];
      return client.listChannelInstructionVersions(channelId);
    },
    {
      enabled: Boolean(channelId) && (options?.enabled ?? true),
      staleTime: 0,
      refetchOnMount: "always",
    },
  );
}

// publish + delete mutations. Both invalidate the latest + versions queries
// so the editor and history dropdown refresh immediately. The publish
// mutation surfaces `FolderInstructionsConflictError` from the client
// unchanged so the UI can show a "reload" prompt.
export function useFolderInstructionsMutations(channelId: string | null) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    if (!channelId) return;
    void queryClient.invalidateQueries({
      queryKey: CHANNEL_INSTRUCTIONS_QUERY_KEY(channelId),
    });
    void queryClient.invalidateQueries({
      queryKey: CHANNEL_INSTRUCTIONS_VERSIONS_QUERY_KEY(channelId),
    });
  }, [channelId, queryClient]);

  const publishMutation = useMutation({
    mutationFn: async (input: { content: string; baseVersion: number }) => {
      if (!client) throw new Error("Not authenticated");
      if (!channelId) throw new Error("No channel id");
      return client.putChannelInstructions(channelId, {
        content: input.content,
        baseVersion: input.baseVersion,
      });
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      if (!channelId) throw new Error("No channel id");
      return client.deleteChannelInstructions(channelId);
    },
    onSuccess: invalidate,
  });

  const publish = useCallback(
    (input: { content: string; baseVersion: number }) =>
      publishMutation.mutateAsync(input),
    [publishMutation],
  );

  const remove = useCallback(
    () => deleteMutation.mutateAsync(),
    [deleteMutation],
  );

  return {
    publish,
    remove,
    isPublishing: publishMutation.isPending,
    isDeleting: deleteMutation.isPending,
    publishError: publishMutation.error,
  };
}
