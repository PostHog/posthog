import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

// File bodies (and especially base64 blobs) are the largest payloads in the
// query cache; the default 5-minute gcTime keeps every file viewed across
// every task resident simultaneously. Drop unobserved entries quickly — a
// re-open re-reads from local disk, which is cheap.
const FILE_CONTENT_GC_MS = 30 * 1000;

export function useRepoFileContent(
  repoPath: string,
  filePath: string,
  enabled: boolean,
) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.fs.readRepoFile.queryOptions(
      { repoPath, filePath },
      {
        enabled,
        staleTime: Number.POSITIVE_INFINITY,
        gcTime: FILE_CONTENT_GC_MS,
      },
    ),
  );
}

export function useAbsoluteFileContent(filePath: string, enabled: boolean) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.fs.readAbsoluteFile.queryOptions(
      { filePath },
      {
        enabled,
        staleTime: Number.POSITIVE_INFINITY,
        gcTime: FILE_CONTENT_GC_MS,
      },
    ),
  );
}

export function useFileAsBase64(filePath: string, enabled: boolean) {
  const trpc = useHostTRPC();
  return useQuery(
    trpc.fs.readFileAsBase64.queryOptions(
      { filePath },
      {
        enabled,
        staleTime: Number.POSITIVE_INFINITY,
        gcTime: FILE_CONTENT_GC_MS,
      },
    ),
  );
}
