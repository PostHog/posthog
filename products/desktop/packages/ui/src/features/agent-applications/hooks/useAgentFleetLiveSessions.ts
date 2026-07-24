import type { AgentFleetLiveSessionsResponse } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

const EMPTY: AgentFleetLiveSessionsResponse = { results: [] };

/**
 * Cross-agent live (non-terminal) sessions. Polls aggressively (5s) since live
 * sessions move fast; react-query pauses when the tab is unfocused.
 */
export function useAgentFleetLiveSessions(limit?: number) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentFleetLiveSessionsResponse>(
    [...agentApplicationsKeys.fleetLiveSessions(projectId), limit ?? null],
    (client) =>
      projectId
        ? client.listAgentFleetLiveSessions(limit)
        : Promise.resolve(EMPTY),
    {
      enabled: !!projectId,
      staleTime: 5_000,
      refetchInterval: 5_000,
    },
  );
}
