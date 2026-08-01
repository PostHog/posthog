import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Names of env keys currently set on a revision (values are never returned).
 * Env keys are revision-scoped, so callers must pass the revision in scope.
 */
export function useAgentEnvKeys(idOrSlug: string, revisionId: string | null) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<string[]>(
    agentApplicationsKeys.envKeys(projectId, idOrSlug, revisionId),
    (client) => client.listAgentEnvKeys(idOrSlug, revisionId as string),
    {
      enabled: !!projectId && !!idOrSlug && !!revisionId,
      staleTime: 15_000,
    },
  );
}
