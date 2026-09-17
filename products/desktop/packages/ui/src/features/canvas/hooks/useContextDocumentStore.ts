import {
  ContextWikiConflictError,
  FolderInstructionsConflictError,
} from "@posthog/api-client/posthog-client";
import {
  useFolderInstructions,
  useFolderInstructionsMutations,
} from "@posthog/ui/features/canvas/hooks/useFolderInstructions";
import {
  useContextWikiPage,
  useContextWikiPageMutation,
} from "@posthog/ui/features/context-wiki/hooks/useContextWiki";
import { useCallback } from "react";

export interface ContextDocumentStore {
  content: string;
  isLoading: boolean;
  isRefreshing: boolean;
  error: Error | null;
  updatedAt: string | null;
  save: (content: string) => Promise<void>;
  isSaving: boolean;
  saveError: Error | null;
  isConflict: boolean;
  refetch: () => void;
}

export function useLegacyContextDocumentStore(
  channelId: string,
): ContextDocumentStore {
  const latest = useFolderInstructions(channelId, { pollWhileEmpty: true });
  const { publish, isPublishing, publishError } =
    useFolderInstructionsMutations(channelId);
  const version = latest.data?.version ?? 0;
  const refetch = latest.refetch;

  const save = useCallback(
    async (content: string) => {
      await publish({ content, baseVersion: version });
    },
    [publish, version],
  );

  return {
    content: latest.data?.content ?? "",
    isLoading: latest.isLoading,
    isRefreshing: latest.isFetching && !latest.isLoading,
    error: latest.error,
    updatedAt: latest.data?.created_at ?? null,
    save,
    isSaving: isPublishing,
    saveError: publishError,
    isConflict: publishError instanceof FolderInstructionsConflictError,
    refetch: () => void refetch(),
  };
}

export function useWikiContextDocumentStore(
  path: string,
): ContextDocumentStore {
  const page = useContextWikiPage(path);
  const mutation = useContextWikiPageMutation();
  const head = page.data?.head_sha ?? null;
  const refetch = page.refetch;
  const mutateAsync = mutation.mutateAsync;

  const save = useCallback(
    async (content: string) => {
      if (page.isLoading) throw new Error("The page has not loaded yet.");
      await mutateAsync({ path, content, baseHead: head ?? undefined });
    },
    [mutateAsync, path, head, page.isLoading],
  );

  return {
    content: page.data?.content ?? "",
    isLoading: page.isLoading,
    isRefreshing: page.isFetching && !page.isLoading,
    error: page.error,
    updatedAt: page.data?.updated_at ?? null,
    save,
    isSaving: mutation.isPending,
    saveError: mutation.error,
    isConflict: mutation.error instanceof ContextWikiConflictError,
    refetch: () => void refetch(),
  };
}
