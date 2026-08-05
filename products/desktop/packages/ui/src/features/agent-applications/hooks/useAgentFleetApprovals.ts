import type {
  AgentApprovalRequest,
  AgentApprovalsListParams,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";
import { isApprovalsPermissionError } from "./approvalsPermission";

/**
 * Fleet-wide tool-approval requests across every agent on the team
 * (organization-admin only). Optionally filtered to a single state; omit for
 * all. `isPermissionError` is true when the viewer lacks admin access.
 */
export function useAgentFleetApprovals(params?: AgentApprovalsListParams) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const query = useAuthenticatedQuery<AgentApprovalRequest[]>(
    agentApplicationsKeys.fleetApprovals(projectId, params?.state),
    (client) => client.listAgentFleetApprovals(params),
    {
      enabled: !!projectId,
      staleTime: 10_000,
      // Stop polling once we know the viewer lacks org-admin access.
      refetchInterval: (q) =>
        isApprovalsPermissionError(q.state.error) ? false : 10_000,
      // A 404 here is the admin gate, not a transient failure — don't retry.
      retry: (failureCount, error) =>
        !isApprovalsPermissionError(error) && failureCount < 3,
    },
  );
  return {
    ...query,
    isPermissionError: isApprovalsPermissionError(query.error),
  };
}
