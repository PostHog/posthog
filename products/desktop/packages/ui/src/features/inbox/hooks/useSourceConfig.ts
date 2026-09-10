import type { SourceConfig } from "@posthog/api-client/posthog-client";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";

/**
 * Fetch the connect-form field schema for a single external data source type
 * (e.g. `"Jira"`) from the warehouse wizard endpoint, so setup forms can be
 * rendered from the backend's field definitions instead of being hardcoded.
 */
export function useSourceConfig(sourceType: string | null) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<SourceConfig | null>(
    ["external-data-source-config", projectId, sourceType],
    async (client) => {
      if (!projectId || !sourceType) return null;
      const configs = await client.getExternalDataSourceConfigs(
        projectId,
        sourceType,
      );
      return configs[sourceType] ?? null;
    },
    { enabled: !!projectId && !!sourceType, staleTime: 300_000 },
  );
}
