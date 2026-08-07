import type { AgentApplication } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** Fetches a single agent application by UUID or slug. */
export function useAgentApplication(idOrSlug: string) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentApplication | null>(
    agentApplicationsKeys.detail(projectId, idOrSlug),
    (client) => client.getAgentApplication(idOrSlug),
    { enabled: !!projectId && !!idOrSlug, staleTime: 30_000 },
  );
}
