import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

interface UseLinkedBranchPrUrlArgs {
  linkedBranch: string | null;
  folderPath: string | null;
}

/**
 * Resolves the PR URL for a local task's linked branch by looking it up via
 * `gh pr list --head`. Returns `null` when the task has no linked branch, no
 * folder path, or the branch has no associated PR on GitHub.
 */
export function useLinkedBranchPrUrl({
  linkedBranch,
  folderPath,
}: UseLinkedBranchPrUrlArgs): string | null {
  const trpc = useHostTRPC();
  const { data } = useQuery({
    ...trpc.git.getPrUrlForBranch.queryOptions({
      directoryPath: folderPath as string,
      branchName: linkedBranch as string,
    }),
    enabled: !!folderPath && !!linkedBranch,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  return data ?? null;
}
