import type { AgentApplicationSessionDetail } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

const TERMINAL_STATES = new Set(["completed", "closed", "cancelled", "failed"]);

/** Fetches one session's detail, including its stored conversation transcript. */
export function useAgentApplicationSession(
  idOrSlug: string,
  sessionId: string,
  lastN?: number,
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentApplicationSessionDetail | null>(
    [
      ...agentApplicationsKeys.session(projectId, idOrSlug, sessionId),
      lastN ?? null,
    ],
    (client) =>
      projectId
        ? client.getAgentApplicationSession(idOrSlug, sessionId, lastN)
        : Promise.resolve(null),
    {
      enabled: !!projectId && !!idOrSlug && !!sessionId,
      staleTime: 15_000,
      // Poll only while the session is still active; terminal sessions are immutable.
      refetchInterval: (query) =>
        query.state.data && !TERMINAL_STATES.has(query.state.data.state)
          ? 10_000
          : false,
    },
  );
}
