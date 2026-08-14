import type {
  AgentApprovalRequest,
  AgentApprovalsListParams,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";
import { isApprovalsPermissionError } from "./approvalsPermission";

/**
 * Lists tool-approval requests for one agent (organization-admin only).
 * Optionally filtered to a single state (the backend accepts one `state`
 * value); omit for all states. `isPermissionError` is true when the viewer
 * lacks admin access.
 */
export function useAgentApplicationApprovals(
  idOrSlug: string,
  params?: AgentApprovalsListParams,
) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const query = useAuthenticatedQuery<AgentApprovalRequest[]>(
    agentApplicationsKeys.approvals(projectId, idOrSlug, params?.state),
    (client) => client.listAgentApplicationApprovals(idOrSlug, params),
    {
      enabled: !!projectId && !!idOrSlug,
      staleTime: 10_000,
      // Queued approvals change as agents run; poll while the tab is focused —
      // but stop once we know the viewer lacks org-admin access.
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
