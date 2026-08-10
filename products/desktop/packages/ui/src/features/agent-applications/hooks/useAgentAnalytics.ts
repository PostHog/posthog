import type { AgentAnalyticsData } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Agent observability rollup over the team's own `$ai_*` events. Pass an
 * `applicationId` (the agent's UUID) to scope the board to a single agent (the
 * per-agent Observability tab); omit it for the fleet-wide analytics board.
 *
 * The fleet board is enabled as soon as a project is selected; the per-agent
 * board waits for the resolved `applicationId` so it doesn't fetch an
 * unscoped (whole-fleet) board for one agent's tab.
 */
export function useAgentAnalytics(applicationId?: string, scope?: "agent") {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const enabled = !!projectId && (scope !== "agent" || !!applicationId);
  return useAuthenticatedQuery<AgentAnalyticsData>(
    agentApplicationsKeys.analytics(projectId, applicationId),
    (client) => client.getAgentAnalytics(applicationId),
    { enabled, staleTime: 30_000 },
  );
}
