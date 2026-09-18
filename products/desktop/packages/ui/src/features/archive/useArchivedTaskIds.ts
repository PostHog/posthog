import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useServerArchiveScope } from "./useServerArchiveScope";

export function useArchivedTaskIds(): Set<string> {
  const trpc = useHostTRPC();
  const serverArchiveScope = useServerArchiveScope();
  const { data } = useQuery(
    trpc.archive.archivedTaskIds.queryOptions({ serverArchiveScope }),
  );
  return useMemo(() => new Set(data ?? []), [data]);
}
