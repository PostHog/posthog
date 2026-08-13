import type { GitStateSnapshot } from "@posthog/core/git/router-schemas";
import { resolveService } from "@posthog/di/container";
import type { QueryClient } from "@tanstack/react-query";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "../gitCacheProvider";

export function updateGitCacheFromSnapshot(
  queryClient: QueryClient,
  repoPath: string,
  snapshot: GitStateSnapshot,
): void {
  const provider = resolveService<GitCacheKeyProvider>(GIT_CACHE_KEY_PROVIDER);
  const input = { directoryPath: repoPath };

  if (snapshot.changedFiles !== undefined) {
    queryClient.setQueryData(
      provider.gitQueryKey("getChangedFilesHead", input),
      snapshot.changedFiles,
    );
  }

  if (snapshot.diffStats !== undefined) {
    queryClient.setQueryData(
      provider.gitQueryKey("getDiffStats", input),
      snapshot.diffStats,
    );
  }

  if (snapshot.syncStatus !== undefined) {
    queryClient.setQueryData(
      provider.gitQueryKey("getGitSyncStatus", input),
      snapshot.syncStatus,
    );
    if (snapshot.syncStatus.currentBranch !== undefined) {
      queryClient.setQueryData(
        provider.gitQueryKey("getCurrentBranch", input),
        snapshot.syncStatus.currentBranch,
      );
    }
  }

  if (snapshot.latestCommit !== undefined) {
    queryClient.setQueryData(
      provider.gitQueryKey("getLatestCommit", input),
      snapshot.latestCommit,
    );
  }

  if (snapshot.prStatus !== undefined) {
    queryClient.setQueryData(
      provider.gitQueryKey("getPrStatus", input),
      snapshot.prStatus,
    );
  }
}
