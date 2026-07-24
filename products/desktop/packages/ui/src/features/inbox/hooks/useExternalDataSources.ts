import type { ExternalDataSource } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";

export function useExternalDataSources() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ExternalDataSource[]>(
    ["external-data-sources", projectId],
    (client) =>
      projectId
        ? client.listExternalDataSources(projectId)
        : Promise.resolve([]),
    { enabled: !!projectId, staleTime: 60_000 },
  );
}
