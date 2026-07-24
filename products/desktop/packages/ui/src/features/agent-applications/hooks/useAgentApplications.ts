import type { AgentApplication } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** Lists the deployed agent applications for the current project. */
export function useAgentApplications() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentApplication[]>(
    agentApplicationsKeys.list(projectId),
    (client) =>
      projectId ? client.listAgentApplications() : Promise.resolve([]),
    { enabled: !!projectId, staleTime: 30_000 },
  );
}
