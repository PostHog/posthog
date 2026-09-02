import { useHostTRPC } from "@posthog/host-router/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

export function useFolders() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const foldersQueryKey = trpc.folders.getFolders.queryKey();

  const { data: folders = [], isLoading } = useQuery(
    trpc.folders.getFolders.queryOptions(undefined, { staleTime: 30_000 }),
  );

  const existingFolders = useMemo(
    () => folders.filter((f) => f.exists !== false),
    [folders],
  );

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: foldersQueryKey });
  }, [queryClient, foldersQueryKey]);

  const addFolderMutation = useMutation(
    trpc.folders.addFolder.mutationOptions({ onSuccess: invalidate }),
  );

  const removeFolderMutation = useMutation(
    trpc.folders.removeFolder.mutationOptions({ onSuccess: invalidate }),
  );

  const updateAccessedMutation = useMutation(
    trpc.folders.updateFolderAccessed.mutationOptions(),
  );

  const addFolder = useCallback(
    (folderPath: string) => addFolderMutation.mutateAsync({ folderPath }),
    [addFolderMutation],
  );

  const removeFolder = useCallback(
    (folderId: string) => removeFolderMutation.mutateAsync({ folderId }),
    [removeFolderMutation],
  );

  const updateLastAccessed = useCallback(
    (folderId: string) => {
      updateAccessedMutation.mutate({ folderId });
    },
    [updateAccessedMutation],
  );

  const getFolderByPath = useCallback(
    (path: string) => existingFolders.find((f) => f.path === path),
    [existingFolders],
  );

  const getRecentFolders = useCallback(
    (limit = 10) =>
      [...existingFolders]
        .sort(
          (a, b) =>
            new Date(b.lastAccessed).getTime() -
            new Date(a.lastAccessed).getTime(),
        )
        .slice(0, limit),
    [existingFolders],
  );

  const getFolderDisplayName = useCallback(
    (path: string) => {
      if (!path) return null;
      const folder = existingFolders.find((f) => f.path === path);
      return folder?.name ?? path.split("/").pop() ?? null;
    },
    [existingFolders],
  );

  const loadFolders = useCallback(() => invalidate(), [invalidate]);

  return {
    folders: existingFolders,
    isLoaded: !isLoading,
    addFolder,
    removeFolder,
    updateLastAccessed,
    getFolderByPath,
    getRecentFolders,
    getFolderDisplayName,
    loadFolders,
  };
}
