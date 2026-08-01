import type {
  FolderInstructions,
  FolderInstructionsVersion,
} from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const FOLDER_INSTRUCTIONS_QUERY_KEY = (folderId: string) =>
  ["folder-instructions", folderId] as const;

const FOLDER_INSTRUCTIONS_VERSIONS_QUERY_KEY = (folderId: string) =>
  ["folder-instructions", folderId, "versions"] as const;

// While a context has no published CONTEXT.md, `pollWhileEmpty` views refetch
// on this cadence so an agent's mid-run publish (via the MCP) appears without
// a manual reload. Polling stops as soon as content exists.
const FOLDER_INSTRUCTIONS_EMPTY_POLL_INTERVAL_MS = 5_000;

// Latest published version, or `null` when none exists yet. The latest
// content is what the editor opens with; the editor never edits an old
// version in-place, it republishes from current latest.
export function useFolderInstructions(
  folderId: string | null,
  options?: { enabled?: boolean; pollWhileEmpty?: boolean },
) {
  return useAuthenticatedQuery<FolderInstructions | null>(
    folderId
      ? FOLDER_INSTRUCTIONS_QUERY_KEY(folderId)
      : (["folder-instructions", "none"] as const),
    async (client) => {
      if (!folderId) return null;
      return client.getDesktopFolderInstructions(folderId);
    },
    {
      enabled: Boolean(folderId) && (options?.enabled ?? true),
      // Always refetch on mount so opening CONTEXT.md after another user (or
      // an agent) edited it from elsewhere shows the current content, not the
      // last-cached body.
      staleTime: 0,
      refetchOnMount: "always",
      refetchInterval: options?.pollWhileEmpty
        ? (query) =>
            (query.state.data?.content ?? "").trim().length > 0
              ? false
              : FOLDER_INSTRUCTIONS_EMPTY_POLL_INTERVAL_MS
        : undefined,
    },
  );
}

// Newest-first list of version metadata (no content) — used by the version
// dropdown. The list refetches after every publish/delete via the same key
// invalidation in the mutations hook below.
export function useFolderInstructionsVersions(
  folderId: string | null,
  options?: { enabled?: boolean },
) {
  return useAuthenticatedQuery<FolderInstructionsVersion[]>(
    folderId
      ? FOLDER_INSTRUCTIONS_VERSIONS_QUERY_KEY(folderId)
      : (["folder-instructions", "none", "versions"] as const),
    async (client) => {
      if (!folderId) return [];
      return client.listDesktopFolderInstructionVersions(folderId);
    },
    {
      enabled: Boolean(folderId) && (options?.enabled ?? true),
    },
  );
}

// publish + delete mutations. Both invalidate the latest + versions queries
// so the editor and history dropdown refresh immediately. The publish
// mutation surfaces `FolderInstructionsConflictError` from the client
// unchanged so the UI can show a "reload" prompt.
export function useFolderInstructionsMutations(folderId: string | null) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  const invalidate = useCallback(() => {
    if (!folderId) return;
    void queryClient.invalidateQueries({
      queryKey: FOLDER_INSTRUCTIONS_QUERY_KEY(folderId),
    });
    void queryClient.invalidateQueries({
      queryKey: FOLDER_INSTRUCTIONS_VERSIONS_QUERY_KEY(folderId),
    });
  }, [folderId, queryClient]);

  const publishMutation = useMutation({
    mutationFn: async (input: { content: string; baseVersion: number }) => {
      if (!client) throw new Error("Not authenticated");
      if (!folderId) throw new Error("No folder id");
      return client.putDesktopFolderInstructions(folderId, {
        content: input.content,
        base_version: input.baseVersion,
      });
    },
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      if (!folderId) throw new Error("No folder id");
      return client.deleteDesktopFolderInstructions(folderId);
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
