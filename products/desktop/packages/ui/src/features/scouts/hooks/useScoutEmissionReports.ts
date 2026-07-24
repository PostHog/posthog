import type { ScoutEmissionReportLink } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";
import { useMemo } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * Best-effort reverse lookup of which inbox report each finding grouped into,
 * for every run in the window. Loaded alongside {@link useScoutRunEmissions} in a
 * single batched request (one ClickHouse round-trip); the caller keys the result
 * by `source_id` to adorn each emission card. A failure here is non-fatal — the
 * cards still render, just without the report chip.
 */
export function useScoutEmissionReports(runIds: string[]) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  // Sort so the cache key is stable regardless of run ordering.
  const sortedRunIds = useMemo(() => [...runIds].sort(), [runIds]);
  return useAuthenticatedQuery<ScoutEmissionReportLink[]>(
    scoutQueryKeys.emissionReports(projectId, sortedRunIds),
    (client) =>
      projectId
        ? client.batchScoutEmissionReports(projectId, sortedRunIds)
        : Promise.resolve([]),
    {
      enabled: !!projectId && sortedRunIds.length > 0,
      staleTime: 60_000,
      placeholderData: keepPreviousData,
    },
  );
}
