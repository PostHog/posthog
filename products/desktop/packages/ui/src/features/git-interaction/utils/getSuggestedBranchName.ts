import {
  deriveBranchName,
  suggestBranchName,
} from "@posthog/core/git-interaction/branchName";
import type { Task } from "@posthog/shared/domain-types";
import type { QueryClient } from "@tanstack/react-query";
import type { GitCacheKeyProvider } from "../gitCacheProvider";

export function getSuggestedBranchName(
  queryClient: QueryClient,
  provider: GitCacheKeyProvider,
  taskId: string,
  repoPath?: string,
): string {
  const queries = queryClient.getQueriesData<Task[]>({
    queryKey: ["tasks", "list"],
  });
  let task: Task | undefined;
  for (const [, tasks] of queries) {
    task = tasks?.find((t) => t.id === taskId);
    if (task) break;
  }
  const fallbackId = task?.task_number
    ? String(task.task_number)
    : (task?.slug ?? taskId);

  if (!repoPath) return deriveBranchName(task?.title ?? "", fallbackId);

  const cached =
    queryClient.getQueryData<string[]>(
      provider.gitQueryKey("getAllBranches", { directoryPath: repoPath }),
    ) ?? [];

  return suggestBranchName(task?.title ?? "", fallbackId, cached);
}
