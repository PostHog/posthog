import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import {
  readQuerySnapshot,
  useWriteQuerySnapshot,
} from "@posthog/ui/hooks/useQuerySnapshot";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

export function useScoutConfigs() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const snapshot = `scouts.configs.${projectId ?? "none"}`;
  const query = useAuthenticatedQuery<ScoutConfig[]>(
    scoutQueryKeys.configs(projectId),
    (client) =>
      projectId ? client.listScoutConfigs(projectId) : Promise.resolve([]),
    // Polled like the sibling runs query: the inactivity sweep and the failure
    // breaker move `status` with no client involvement, so a fleet page left
    // open would otherwise show a stale lifecycle until it regained focus.
    // The snapshot paints the last known fleet at once; `0` marks it stale, so
    // a refresh always follows it.
    {
      enabled: !!projectId,
      staleTime: 30_000,
      refetchInterval: 60_000,
      initialData: () => readQuerySnapshot<ScoutConfig[]>(snapshot),
      initialDataUpdatedAt: 0,
    },
  );
  useWriteQuerySnapshot(snapshot, query.data, !query.isFetching);
  return query;
}
