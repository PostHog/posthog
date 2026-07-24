import type { ScoutEmission } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * Every supplied run's emitted findings in one batched request, flattened
 * newest-first (each row keeps its `run_id` so the caller can regroup). Replaces
 * the old per-run fan-out — one request for the whole window instead of one per
 * run. Previous results are kept while a widened window refetches so growing the
 * window doesn't blank the already-rendered cards.
 */
export function useScoutRunEmissions(runIds: string[]) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  // Sort so the cache key is stable regardless of run ordering.
  const sortedRunIds = useMemo(() => [...runIds].sort(), [runIds]);
  return useAuthenticatedQuery<ScoutEmission[]>(
    scoutQueryKeys.emissions(projectId, sortedRunIds),
    (client) =>
      projectId
        ? client.batchScoutRunEmissions(projectId, sortedRunIds)
        : Promise.resolve([]),
    {
      enabled: !!projectId && sortedRunIds.length > 0,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    },
  );
}
