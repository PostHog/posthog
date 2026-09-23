import type { LinearTeam } from "@posthog/api-client/posthog-client";
import { resolveLinearIntegrationId } from "@posthog/core/integrations/linearSourceTeams";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useExternalDataSources } from "@posthog/ui/features/inbox/hooks/useExternalDataSources";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

interface UseLinearTeamsResult {
  teams: LinearTeam[];
  isLoading: boolean;
  /** True once the integration list has landed and carries no Linear connection. */
  missingIntegration: boolean;
  error: Error | null;
}

/**
 * The teams of the Linear workspace the inbox source syncs, for the scope picker. A null
 * integration id means the lists are still loading or Linear is not connected — the two are
 * told apart by whether the integrations query has settled, so a reload never reads as
 * "disconnected".
 */
export function useLinearTeams(enabled: boolean): UseLinearTeamsResult {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { data: sources } = useExternalDataSources();
  const integrationsQuery = useAuthenticatedQuery(
    ["integrations", projectId],
    (client) =>
      projectId
        ? client.getIntegrationsForProject(projectId)
        : Promise.resolve([]),
    { enabled: enabled && !!projectId, staleTime: 60_000 },
  );

  const integrationId = integrationsQuery.data
    ? resolveLinearIntegrationId(integrationsQuery.data, sources)
    : null;

  const teamsQuery = useAuthenticatedQuery<LinearTeam[]>(
    ["integrations", projectId, "linear-teams", integrationId],
    (client) =>
      projectId && integrationId !== null
        ? client.listLinearTeams(projectId, integrationId)
        : Promise.resolve([]),
    {
      enabled: enabled && !!projectId && integrationId !== null,
      staleTime: 300_000,
    },
  );

  return {
    teams: teamsQuery.data ?? [],
    isLoading:
      integrationsQuery.isPending ||
      (integrationId !== null && teamsQuery.isPending),
    missingIntegration: !!integrationsQuery.data && integrationId === null,
    error: teamsQuery.error ?? integrationsQuery.error,
  };
}
