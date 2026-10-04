import type { LinearTeam } from "@posthog/api-client/posthog-client";
import { resolveLinearIntegrationId } from "@posthog/core/integrations/linearSourceTeams";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useExternalDataSources } from "@posthog/ui/features/inbox/hooks/useExternalDataSources";
import { useIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/**
 * `missing` means the integration list landed and carries no Linear connection, which is not
 * the same as a list that has not loaded yet.
 */
export type LinearTeamsStatus = "loading" | "missing" | "error" | "ready";

/** The teams of the Linear workspace the inbox source syncs, for the scope picker. */
export function useLinearTeams(enabled: boolean): {
  teams: LinearTeam[];
  status: LinearTeamsStatus;
} {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { data: sources } = useExternalDataSources();
  const integrationsQuery = useIntegrations();

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

  const status = ((): LinearTeamsStatus => {
    if (integrationsQuery.isPending) return "loading";
    if (integrationsQuery.error) return "error";
    if (integrationId === null) return "missing";
    if (teamsQuery.isPending) return "loading";
    if (teamsQuery.error) return "error";
    return "ready";
  })();

  return { teams: teamsQuery.data ?? [], status };
}
