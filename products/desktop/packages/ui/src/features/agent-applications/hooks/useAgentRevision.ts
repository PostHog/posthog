import type { AgentRevision } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** Fetches a single revision (carries the agent `spec`). */
export function useAgentRevision(
  idOrSlug: string,
  revisionId: string | null | undefined,
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentRevision | null>(
    agentApplicationsKeys.revision(projectId, idOrSlug, revisionId ?? ""),
    (client) =>
      revisionId
        ? client.getAgentRevision(idOrSlug, revisionId)
        : Promise.resolve(null),
    { enabled: !!projectId && !!idOrSlug && !!revisionId, staleTime: 30_000 },
  );
}
