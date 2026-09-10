import { parsePatchFiles } from "@pierre/diffs";
import { contentHash } from "@posthog/core/code-review/contentHash";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useDiffViewerStore } from "../../code-editor/diffViewerStore";
import { invalidateGitWorkingTreeQueries } from "../../git-interaction/gitCacheKeys";
import { useGitQueries } from "../../git-interaction/useGitQueries";
import { makeFileKey } from "../../git-interaction/utils/fileKey";

export function useReviewDiffs(
  repoPath: string | undefined,
  isActive: boolean,
) {
  const trpc = useHostTRPC();
  const { changedFiles, changesLoading } = useGitQueries(repoPath, {
    enabled: isActive,
  });
  const hideWhitespace = useDiffViewerStore((s) => s.hideWhitespaceChanges);

  const hasStagedFiles = useMemo(
    () => changedFiles.some((f) => f.staged),
    [changedFiles],
  );

  const {
    data: rawDiffCached,
    isLoading: diffCachedLoading,
    refetch: refetchDiffCached,
  } = useQuery(
    trpc.git.getDiffCached.queryOptions(
      {
        directoryPath: repoPath as string,
        ignoreWhitespace: hideWhitespace,
      },
      {
        enabled: isActive && !!repoPath,
        staleTime: 30_000,
        gcTime: 0,
        refetchOnMount: "always",
      },
    ),
  );

  const {
    data: rawDiffUnstaged,
    isLoading: diffUnstagedLoading,
    refetch: refetchDiffUnstaged,
  } = useQuery(
    trpc.git.getDiffUnstaged.queryOptions(
      {
        directoryPath: repoPath as string,
        ignoreWhitespace: hideWhitespace,
      },
      {
        enabled: isActive && !!repoPath,
        staleTime: 30_000,
        gcTime: 0,
        refetchOnMount: "always",
      },
    ),
  );

  const diffLoading = diffUnstagedLoading || diffCachedLoading;

  const stagedParsedFiles = useMemo(
    () =>
      rawDiffCached
        ? parsePatchFiles(
            rawDiffCached,
            `staged:${contentHash(rawDiffCached)}`,
          ).flatMap((p) => p.files)
        : [],
    [rawDiffCached],
  );

  const unstagedParsedFiles = useMemo(
    () =>
      rawDiffUnstaged
        ? parsePatchFiles(
            rawDiffUnstaged,
            `unstaged:${contentHash(rawDiffUnstaged)}`,
          ).flatMap((p) => p.files)
        : [],
    [rawDiffUnstaged],
  );

  const untrackedFiles = useMemo(
    () => changedFiles.filter((f) => f.status === "untracked").slice(0, 1000),
    [changedFiles],
  );

  const totalFileCount =
    stagedParsedFiles.length +
    unstagedParsedFiles.length +
    untrackedFiles.length;

  const allPaths = useMemo(
    () => [
      ...stagedParsedFiles.map((f) =>
        makeFileKey(true, f.name ?? f.prevName ?? ""),
      ),
      ...unstagedParsedFiles.map((f) =>
        makeFileKey(false, f.name ?? f.prevName ?? ""),
      ),
      ...untrackedFiles.map((f) => makeFileKey(f.staged, f.path)),
    ],
    [stagedParsedFiles, unstagedParsedFiles, untrackedFiles],
  );

  const refetch = useCallback(() => {
    if (repoPath) invalidateGitWorkingTreeQueries(repoPath);
    refetchDiffUnstaged();
    refetchDiffCached();
  }, [repoPath, refetchDiffCached, refetchDiffUnstaged]);

  return {
    changedFiles,
    changesLoading,
    hasStagedFiles,
    stagedParsedFiles,
    unstagedParsedFiles,
    untrackedFiles,
    totalFileCount,
    allPaths,
    diffLoading,
    refetch,
  };
}
