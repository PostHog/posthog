import { resolveService } from "@posthog/di/container";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "./gitCacheProvider";

export function invalidateGitWorkingTreeQueries(repoPath: string) {
  const queryClient = resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  );
  const provider = resolveService<GitCacheKeyProvider>(GIT_CACHE_KEY_PROVIDER);
  const input = { directoryPath: repoPath };
  queryClient.invalidateQueries(
    provider.gitQueryFilter("getChangedFilesHead", input),
  );
  queryClient.invalidateQueries(provider.gitQueryFilter("getDiffStats", input));
  queryClient.invalidateQueries(provider.gitPathFilter("getDiffCached"));
  queryClient.invalidateQueries(provider.gitPathFilter("getDiffUnstaged"));
}

export function invalidateGitBranchQueries(repoPath: string) {
  // A branch/index change (stage, commit, checkout) also changes the working
  // tree, so the diff and changed-file queries must refresh too.
  invalidateGitWorkingTreeQueries(repoPath);

  const queryClient = resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  );
  const provider = resolveService<GitCacheKeyProvider>(GIT_CACHE_KEY_PROVIDER);
  const input = { directoryPath: repoPath };
  queryClient.invalidateQueries(
    provider.gitQueryFilter("getCurrentBranch", input),
  );
  queryClient.invalidateQueries(
    provider.gitQueryFilter("getAllBranches", input),
  );
  queryClient.invalidateQueries(
    provider.gitQueryFilter("getGitBusyState", input),
  );
  queryClient.invalidateQueries(
    provider.gitQueryFilter("getGitSyncStatus", input),
  );
  queryClient.invalidateQueries(
    provider.gitQueryFilter("getLatestCommit", input),
  );
  queryClient.invalidateQueries(provider.gitQueryFilter("getPrStatus", input));
  queryClient.invalidateQueries(provider.gitPathFilter("getFileAtHead"));
  queryClient.invalidateQueries(
    provider.gitPathFilter("getLocalBranchChangedFiles"),
  );
  queryClient.invalidateQueries(provider.gitPathFilter("getPrChangedFiles"));
  queryClient.invalidateQueries(
    provider.gitPathFilter("getBranchChangedFiles"),
  );
}

export function clearGitReviewQueries() {
  const queryClient = resolveService<ImperativeQueryClient>(
    IMPERATIVE_QUERY_CLIENT,
  );
  const provider = resolveService<GitCacheKeyProvider>(GIT_CACHE_KEY_PROVIDER);
  queryClient.removeQueries(provider.gitPathFilter("getDiffCached"));
  queryClient.removeQueries(provider.gitPathFilter("getDiffUnstaged"));
  queryClient.removeQueries(provider.gitPathFilter("getFileAtHead"));
  queryClient.removeQueries(provider.fsPathFilter("readRepoFile"));
  queryClient.removeQueries(provider.fsPathFilter("readRepoFiles"));
  queryClient.removeQueries(provider.fsPathFilter("readRepoFileBounded"));
  queryClient.removeQueries(provider.fsPathFilter("readRepoFilesBounded"));
  queryClient.removeQueries(
    provider.gitPathFilter("getLocalBranchChangedFiles"),
  );
  queryClient.removeQueries(provider.gitPathFilter("getPrChangedFiles"));
  queryClient.removeQueries(provider.gitPathFilter("getPrDetailsByUrl"));
  queryClient.removeQueries(provider.gitPathFilter("getPrReviewComments"));
}
