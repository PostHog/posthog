import type {
  AgentApprovalRequest,
  DecideApprovalRequest,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

interface DecideArgs {
  approvalId: string;
  body: DecideApprovalRequest;
}

type ApprovalCacheSnapshot = [readonly unknown[], unknown][];

/**
 * Approve or reject a queued tool-approval request. Optimistically clears the
 * approval from every cached approvals shape so the in-chat card unmounts
 * immediately (no decide-roundtrip → invalidate → list-refetch lag); restores
 * on failure. On success, refetches the agent's approval lists so the row
 * reflects its outcome, and fires a toast so the caller doesn't have to add
 * post-decide UX.
 */
export function useDecideAgentApproval(idOrSlug: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<
    AgentApprovalRequest,
    Error,
    DecideArgs,
    { snapshot: ApprovalCacheSnapshot }
  >({
    mutationFn: ({ approvalId, body }) =>
      client.decideAgentApproval(idOrSlug, approvalId, body),
    onMutate: async ({ approvalId }) => {
      // Cancel in-flight approvals queries so a slow refetch can't overwrite
      // the optimistic clear after the user has already moved on.
      const prefix = agentApplicationsKeys.approvalsPrefix(projectId, idOrSlug);
      await queryClient.cancelQueries({ queryKey: prefix });
      const snapshot: ApprovalCacheSnapshot =
        queryClient.getQueriesData<unknown>({ queryKey: prefix });
      // One updater for both shapes: chatPendingApproval stores
      // `AgentApprovalRequest | null`; list queries store `AgentApprovalRequest[]`.
      queryClient.setQueriesData<unknown>(
        { queryKey: prefix },
        (old: unknown) => {
          if (old == null) return old;
          if (Array.isArray(old)) {
            return (old as AgentApprovalRequest[]).filter(
              (r) => r.id !== approvalId,
            );
          }
          if (typeof old === "object" && old !== null && "id" in old) {
            return (old as AgentApprovalRequest).id === approvalId ? null : old;
          }
          return old;
        },
      );
      return { snapshot };
    },
    onSuccess: (_data, { body }) => {
      if (body.decision === "approve") {
        toast.success("Approved", {
          description:
            body.edited_args !== undefined
              ? "Dispatched with edited arguments."
              : "Dispatched to the agent.",
        });
      } else {
        toast.success("Rejected", {
          description: "The agent will see the rejection.",
        });
      }
    },
    onError: (err, _vars, context) => {
      // Restore each shape exactly as it was before the optimistic clear.
      if (context?.snapshot) {
        for (const [key, data] of context.snapshot) {
          queryClient.setQueryData(key, data);
        }
      }
      toast.error("Decision failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    },
    onSettled: () => {
      // Converge with server truth — handles next-in-line pending approvals
      // for the same session, and refreshes any state-filtered list views.
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.approvalsPrefix(projectId, idOrSlug),
      });
    },
  });
}
