import type { ContextObject } from "@posthog/core/canvas/contextDocument";
import {
  buildSpaceSignalsQuery,
  parseSpaceSignalRows,
  type SpaceSignal,
} from "@posthog/core/canvas/spaceSignals";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";

export const spaceSignalsQueryKey = (sql: string | null) =>
  ["space-signals", sql ?? ""] as const;

/** The latest raw signals about the objects a space watches. */
export function useSpaceSignals(objects: ContextObject[]) {
  const sql = useMemo(() => buildSpaceSignalsQuery(objects), [objects]);
  return useAuthenticatedQuery<SpaceSignal[]>(
    spaceSignalsQueryKey(sql),
    async (client) => {
      if (!sql) return [];
      const grid = await client.runHogQLQuery(sql);
      return parseSpaceSignalRows(grid.results);
    },
    {
      enabled: sql !== null,
      staleTime: 2 * 60_000,
      retry: false,
    },
  );
}
