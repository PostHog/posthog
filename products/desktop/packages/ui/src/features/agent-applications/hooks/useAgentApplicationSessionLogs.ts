import type {
  AgentSessionLogEntry,
  AgentSessionLogsParams,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Structured runtime logs for one session. `enabled` lets callers defer the
 * fetch until the Logs tab is actually opened.
 */
export function useAgentApplicationSessionLogs(
  idOrSlug: string,
  sessionId: string,
  options?: { enabled?: boolean; params?: AgentSessionLogsParams },
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<AgentSessionLogEntry[]>(
    [
      ...agentApplicationsKeys.sessionLogs(projectId, idOrSlug, sessionId),
      options?.params ?? null,
    ],
    (client) =>
      client.getAgentApplicationSessionLogs(
        idOrSlug,
        sessionId,
        options?.params,
      ),
    {
      enabled:
        !!projectId && !!idOrSlug && !!sessionId && (options?.enabled ?? true),
      staleTime: 10_000,
    },
  );
}
