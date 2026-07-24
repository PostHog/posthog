import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { REVIEW_FILE_CACHE_TIME_MS, REVIEW_MAX_FILE_LINES } from "../constants";

export function useReadRepoFileBounded(
  repoPath: string,
  filePath: string,
  enabled: boolean,
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.fs.readRepoFileBounded.queryOptions(
      { repoPath, filePath, maxLines: REVIEW_MAX_FILE_LINES },
      {
        enabled,
        staleTime: 30_000,
        gcTime: REVIEW_FILE_CACHE_TIME_MS,
      },
    ),
  );
}
