import type {
  AgentApplicationSessionsListResponse,
  AgentSessionsListParams,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

const EMPTY: AgentApplicationSessionsListResponse = { results: [], count: 0 };

/** Lists sessions for an agent application. */
export function useAgentApplicationSessions(
  idOrSlug: string,
  params?: AgentSessionsListParams,
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentApplicationSessionsListResponse>(
    [...agentApplicationsKeys.sessions(projectId, idOrSlug), params ?? null],
    (client) =>
      projectId
        ? client.listAgentApplicationSessions(idOrSlug, params)
        : Promise.resolve(EMPTY),
    {
      enabled: !!projectId && !!idOrSlug,
      staleTime: 15_000,
      // Auto-poll; react-query pauses this while the tab is unfocused.
      refetchInterval: 15_000,
    },
  );
}
