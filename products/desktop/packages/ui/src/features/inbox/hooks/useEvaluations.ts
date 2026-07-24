import type { Evaluation } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";

const POLL_INTERVAL_MS = 5_000;

export function useEvaluations() {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  return useAuthenticatedQuery<Evaluation[]>(
    ["evaluations", projectId],
    (client) =>
      projectId ? client.listEvaluations(projectId) : Promise.resolve([]),
    {
      enabled: !!projectId,
      staleTime: POLL_INTERVAL_MS,
      refetchInterval: POLL_INTERVAL_MS,
    },
  );
}
