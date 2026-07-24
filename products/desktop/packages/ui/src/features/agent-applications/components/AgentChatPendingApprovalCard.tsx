import { ArrowSquareOutIcon, LockKeyIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type {
  AgentApprovalRequest,
  DecideApprovalRequest,
} from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { toast } from "@posthog/ui/primitives/toast";
import { Flex, Text } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "../hooks/agentApplicationsKeys";
import { approvalStateColor, approvalStateLabel } from "../utils/format";
import { AgentApprovalDecisionForm } from "./AgentApprovalDecisionForm";
import { ArgsSection } from "./AgentApprovalDetail";

/**
 * Inline pending-approval card surfaced in the chat pane / agent builder
 * dock. Renders between the conversation and the composer when the
 * agent has paused on an approval-gated tool call.
 *
 * Decision routing follows the approval `type`:
 *   - `principal` (the default) — the person driving this chat IS the session
 *     principal, so they decide right here. The decision posts to the ingress
 *     via the chat session's `decide` (principal-match, not the owner console),
 *     and the open `/listen` stream resumes the chat on approve.
 *   - `agent` — an owner/admin must decide in the console; the card shows that
 *     and links to the Approvals view rather than offering buttons.
 */
export function AgentChatPendingApprovalCard({
  idOrSlug,
  approval,
  decide,
}: {
  idOrSlug: string;
  approval: AgentApprovalRequest;
  /** Chat-session decide (ingress, principal-match) from `useAgentChat`. */
  decide: (approvalId: string, body: DecideApprovalRequest) => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const isOwnerGate = approval.approver_scope?.type === "agent";

  const mutation = useMutation<void, Error, DecideApprovalRequest>({
    mutationFn: (body) => decide(approval.id, body),
    onSuccess: (_data, body) => {
      toast.success(body.decision === "approve" ? "Approved" : "Rejected", {
        description:
          body.decision === "approve"
            ? "Dispatched to the agent."
            : "The agent will see the rejection.",
      });
      // Clear the card now rather than waiting for the 2s poll; the server-side
      // row has flipped and the stream resumes the chat on approve.
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.approvalsPrefix(projectId, idOrSlug),
      });
    },
    onError: (err) => {
      toast.error("Decision failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    },
  });

  return (
    <div className="shrink-0 border-(--amber-6) border-t bg-(--amber-2) px-4 pt-3 pb-2">
      <Flex align="start" justify="between" gap="3" className="mb-2">
        <Flex direction="column" gap="1" className="min-w-0">
          <Flex align="center" gap="2" className="min-w-0">
            <LockKeyIcon size={13} className="shrink-0 text-(--amber-11)" />
            <Text className="font-semibold text-[12.5px] text-gray-12">
              Approval needed
            </Text>
            <Badge color={approvalStateColor(approval.state)}>
              {approvalStateLabel(approval.state)}
            </Badge>
            <Text className="truncate font-medium font-mono text-[12.5px] text-gray-12">
              {approval.tool_name}
            </Text>
          </Flex>
          <Text className="text-[11px] text-gray-10">
            expires {formatRelativeTimeShort(approval.expires_at)}
          </Text>
        </Flex>
        <Link
          to="/code/agents/applications/$idOrSlug/approvals"
          params={{ idOrSlug }}
          search={{ request: approval.id }}
          className="inline-flex shrink-0 items-center gap-1 text-[11.5px] text-gray-11 no-underline hover:text-gray-12"
        >
          Open in Approvals
          <ArrowSquareOutIcon size={11} />
        </Link>
      </Flex>
      <ArgsSection label="Proposed arguments" args={approval.proposed_args} />
      {isOwnerGate ? (
        <Text className="text-[11.5px] text-gray-10">
          This call needs an owner or admin to approve it in the console — open
          it in Approvals above.
        </Text>
      ) : (
        <AgentApprovalDecisionForm
          approval={approval}
          busy={mutation.isPending}
          error={
            mutation.isError
              ? mutation.error instanceof Error
                ? mutation.error.message
                : "Decision failed"
              : null
          }
          onSubmit={(body) => mutation.mutate(body)}
        />
      )}
    </div>
  );
}
