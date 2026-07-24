import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

export function useArchivedTaskIds(): Set<string> {
  const trpc = useHostTRPC();
  const { data } = useQuery(trpc.archive.archivedTaskIds.queryOptions());
  return useMemo(() => new Set(data ?? []), [data]);
}
