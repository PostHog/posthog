import { useHostTRPC } from "@posthog/host-router/react";
import { useQuery } from "@tanstack/react-query";

export function useHasImportableConfig(): boolean {
  const trpc = useHostTRPC();
  const { data } = useQuery(
    trpc.onboardingImport.getSummary.queryOptions(undefined, {
      staleTime: 60_000,
    }),
  );
  // Loading and error states must NOT include the import-config step: this
  // gates a step in a flow the user is standing in, and a step that appears
  // while the query is pending and disappears when it settles ejects whoever
  // is on it. Only proven importable config earns the step a place.
  return data !== undefined && data.total > 0;
}
