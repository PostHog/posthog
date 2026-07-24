import type { FileDiffMetadata } from "@pierre/diffs";
import {
  buildExpandedFileDiff,
  canExpandFileDiff,
} from "@posthog/core/code-review/fileDiffExpansion";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { REVIEW_FILE_CACHE_TIME_MS } from "../constants";
import { useReadRepoFileBounded } from "./useReadRepoFileBounded";

export interface ExpandableFileDiffResult {
  fileDiff: FileDiffMetadata;
  tooLarge: boolean;
  pending: boolean;
}

export function useExpandableFileDiff(
  patchFileDiff: FileDiffMetadata,
  repoPath: string | undefined,
  skip: boolean,
  inView = true,
): ExpandableFileDiffResult {
  const trpc = useHostTRPC();
  const filePath = patchFileDiff.name ?? patchFileDiff.prevName ?? "";
  const prevPath = patchFileDiff.prevName ?? filePath;
  const canExpand = canExpandFileDiff(patchFileDiff, repoPath, skip);
  const enabled = canExpand && inView;

  const { data: headContent } = useQuery(
    trpc.git.getFileAtHead.queryOptions(
      { directoryPath: repoPath ?? "", filePath: prevPath },
      {
        enabled,
        staleTime: 30_000,
        gcTime: REVIEW_FILE_CACHE_TIME_MS,
      },
    ),
  );

  const { data: workingResult } = useReadRepoFileBounded(
    repoPath ?? "",
    filePath,
    enabled,
  );

  return useMemo(() => {
    if (!canExpand) {
      return { fileDiff: patchFileDiff, tooLarge: false, pending: false };
    }
    if (!workingResult || headContent === undefined) {
      return { fileDiff: patchFileDiff, tooLarge: false, pending: true };
    }
    if (workingResult.kind === "too-large") {
      return { fileDiff: patchFileDiff, tooLarge: true, pending: false };
    }
    if (workingResult.kind === "missing") {
      return { fileDiff: patchFileDiff, tooLarge: false, pending: false };
    }
    return {
      fileDiff: buildExpandedFileDiff(
        patchFileDiff,
        headContent,
        workingResult.content,
      ),
      tooLarge: false,
      pending: false,
    };
  }, [canExpand, patchFileDiff, headContent, workingResult]);
}
