import { EMPTY_DIFF_STATS } from "@posthog/core/code-review/selectTaskDiffStats";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

const EMPTY_CHANGED_FILES: never[] = [];

const GIT_QUERY_DEFAULTS = {
  staleTime: 30_000,
} as const;

interface UseGitQueriesOptions {
  enabled?: boolean;
}

export function useGitQueries(
  repoPath?: string,
  options?: UseGitQueriesOptions,
) {
  const trpc = useHostTRPC();
  const enabled = !!repoPath && (options?.enabled ?? true);
  const input = { directoryPath: repoPath as string };

  const { data: isRepo = false, isLoading: isRepoLoading } = useQuery(
    trpc.git.validateRepo.queryOptions(input, {
      enabled,
      ...GIT_QUERY_DEFAULTS,
    }),
  );

  const repoEnabled = enabled && isRepo;

  const {
    data: changedFiles = EMPTY_CHANGED_FILES,
    isLoading: changesLoading,
  } = useQuery(
    trpc.git.getChangedFilesHead.queryOptions(input, {
      enabled: repoEnabled,
      ...GIT_QUERY_DEFAULTS,
      refetchOnMount: "always",
      placeholderData: (prev) => prev,
    }),
  );

  const { data: diffStats = EMPTY_DIFF_STATS } = useQuery(
    trpc.git.getDiffStats.queryOptions(input, {
      enabled: repoEnabled,
      ...GIT_QUERY_DEFAULTS,
      placeholderData: (prev) => prev ?? EMPTY_DIFF_STATS,
    }),
  );

  const { data: currentBranchData, isLoading: branchLoading } = useQuery(
    trpc.git.getCurrentBranch.queryOptions(input, {
      enabled: repoEnabled,
      staleTime: 10_000,
      placeholderData: (prev) => prev,
    }),
  );

  const { data: busyState } = useQuery(
    trpc.git.getGitBusyState.queryOptions(input, {
      enabled: repoEnabled,
      staleTime: 5_000,
      refetchInterval: 30_000,
      placeholderData: (prev) => prev,
    }),
  );

  const { data: syncStatus, isLoading: syncLoading } = useQuery(
    trpc.git.getGitSyncStatus.queryOptions(input, {
      enabled: repoEnabled,
      ...GIT_QUERY_DEFAULTS,
      refetchInterval: 60_000,
    }),
  );

  const { data: repoInfo } = useQuery(
    trpc.git.getGitRepoInfo.queryOptions(input, {
      enabled: repoEnabled,
      ...GIT_QUERY_DEFAULTS,
      staleTime: 60_000,
    }),
  );

  const { data: ghStatus } = useQuery(
    trpc.git.getGhStatus.queryOptions(undefined, {
      enabled,
      ...GIT_QUERY_DEFAULTS,
      staleTime: 60_000,
    }),
  );

  const currentBranch = currentBranchData ?? syncStatus?.currentBranch ?? null;

  const { data: prStatus } = useQuery(
    trpc.git.getPrStatus.queryOptions(input, {
      enabled: repoEnabled && !!ghStatus?.installed && !!currentBranch,
      ...GIT_QUERY_DEFAULTS,
    }),
  );

  const { data: latestCommit } = useQuery(
    trpc.git.getLatestCommit.queryOptions(input, {
      enabled: repoEnabled,
      ...GIT_QUERY_DEFAULTS,
    }),
  );

  useQuery(
    trpc.git.getAllBranches.queryOptions(input, {
      enabled: repoEnabled,
      ...GIT_QUERY_DEFAULTS,
      staleTime: 60_000,
    }),
  );

  const hasChanges = changedFiles.length > 0;
  const aheadOfRemote = syncStatus?.aheadOfRemote ?? 0;
  const behind = syncStatus?.behind ?? 0;
  const aheadOfDefault = syncStatus?.aheadOfDefault ?? 0;
  const hasRemote = syncStatus?.hasRemote ?? true;
  const isFeatureBranch = syncStatus?.isFeatureBranch ?? false;
  const defaultBranch = repoInfo?.defaultBranch ?? null;

  return {
    isRepo,
    isRepoLoading,
    changedFiles,
    changesLoading,
    diffStats,
    syncStatus,
    syncLoading,
    repoInfo,
    ghStatus,
    prStatus,
    latestCommit,
    hasChanges,
    aheadOfRemote,
    behind,
    aheadOfDefault,
    hasRemote,
    isFeatureBranch,
    currentBranch,
    branchLoading,
    defaultBranch,
    busyState,
    isLoading: isRepoLoading || changesLoading || syncLoading,
  };
}

export function usePrChangedFiles(prUrl: string | null, pollFast?: boolean) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.git.getPrChangedFiles.queryOptions(
      { prUrl: prUrl as string },
      {
        enabled: !!prUrl,
        staleTime: pollFast ? 10_000 : 5 * 60_000,
        refetchInterval: pollFast ? 10_000 : false,
        placeholderData: (prev) => prev,
        retry: 1,
      },
    ),
  );
}

export function useBranchChangedFiles(
  repo: string | null,
  branch: string | null,
  pollFast?: boolean,
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.git.getBranchChangedFiles.queryOptions(
      { repo: repo as string, branch: branch as string },
      {
        enabled: !!repo && !!branch,
        staleTime: pollFast ? 10_000 : 5 * 60_000,
        refetchInterval: pollFast ? 10_000 : false,
        retry: 1,
      },
    ),
  );
}

export function useLocalBranchChangedFiles(
  directoryPath: string | null,
  branch: string | null,
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.git.getLocalBranchChangedFiles.queryOptions(
      { directoryPath: directoryPath as string, branch: branch as string },
      {
        enabled: !!directoryPath && !!branch,
        staleTime: 30_000,
        refetchOnMount: "always",
        placeholderData: (prev) => prev,
        retry: 1,
      },
    ),
  );
}
