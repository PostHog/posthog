import type { AgentRevision } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** All revisions for an agent (newest first), for the revision picker. */
export function useAgentRevisions(idOrSlug: string) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentRevision[]>(
    agentApplicationsKeys.revisions(projectId, idOrSlug),
    (client) => client.listAgentRevisions(idOrSlug),
    { enabled: !!projectId && !!idOrSlug, staleTime: 30_000 },
  );
}
