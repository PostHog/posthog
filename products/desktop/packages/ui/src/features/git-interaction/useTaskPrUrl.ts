import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useLocalRepoPath } from "../workspace/useLocalRepoPath";
import { useWorkspace } from "../workspace/useWorkspace";
import { useCloudPrUrls } from "./useCloudPrUrl";
import { useLinkedBranchPrUrl } from "./useLinkedBranchPrUrl";
import { resolveTaskPrUrls, type TaskPrUrls } from "./utils/resolveTaskPrUrls";

/**
 * Resolves the PR URLs for a task across all task kinds:
 *   - cloud: the cloud run's accumulated `pr_urls` (first-created first)
 *   - local: the linked-branch lookup, falling back to `getPrStatus` on the
 *     active repo path, plus every PR cached for the task over its lifetime
 *
 * On task switch we prefer the cached PR URLs from the workspaces table so the
 * value is available synchronously — the live `gh` lookups still run and
 * supersede the cache as their values arrive.
 *
 * Shared by the task header (`TaskActionsMenu`) and the command center cell
 * header (`CommandCenterPRButton`) so they always agree on what PR a task
 * points at.
 */
export function useTaskPrUrls(taskId: string, isCloud: boolean): TaskPrUrls {
  const cloudUrls = useCloudPrUrls(taskId);
  const workspace = useWorkspace(taskId);
  const linkedPrUrl = useLinkedBranchPrUrl({
    linkedBranch: workspace?.linkedBranch ?? null,
    folderPath: workspace?.folderPath ?? null,
  });
  const localRepoPath = useLocalRepoPath(taskId);

  const trpc = useHostTRPC();
  const { data: prStatus } = useQuery({
    ...trpc.git.getPrStatus.queryOptions({
      directoryPath: localRepoPath ?? "",
    }),
    enabled: !isCloud && !!localRepoPath,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });

  const { data: cached } = useQuery({
    ...trpc.workspace.getCachedPrUrl.queryOptions({ taskId }),
    enabled: !isCloud,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });

  if (isCloud) {
    return resolveTaskPrUrls({
      cloudUrls,
      cachedUrls: [],
      currentBranchUrl: null,
    });
  }

  return resolveTaskPrUrls({
    cloudUrls,
    cachedUrls: cached?.prUrls ?? [],
    currentBranchUrl: linkedPrUrl ?? prStatus?.prUrl ?? cached?.prUrl ?? null,
  });
}

export function useTaskPrUrl(taskId: string, isCloud: boolean): string | null {
  return useTaskPrUrls(taskId, isCloud).primaryUrl;
}
