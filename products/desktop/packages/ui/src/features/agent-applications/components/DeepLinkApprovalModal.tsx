import { LockKeyIcon } from "@phosphor-icons/react";
import type { DecideApprovalRequest } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { Dialog, Flex, Text } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import type { PendingApprovalDeepLink } from "../hooks/useApprovalDeepLink";
import { agentIngressBaseUrl } from "../utils/ingress";
import { AgentApprovalDecisionForm } from "./AgentApprovalDecisionForm";
import { ArgsSection } from "./AgentApprovalDetail";

/**
 * The approval surface for non-Code channels (MCP, a Slack link): a
 * `<scheme>://approval/<id>?agent=<slug>` deep link opens PostHog into this
 * modal. Fetch + decide go straight to the slug-routed ingress, authenticated
 * as the session principal (the user's bearer) — no project-scoped console call,
 * so it resolves from any project. The link carries only a non-actionable id +
 * slug, never a credential.
 */
export function DeepLinkApprovalModal({
  pending,
  onClose,
}: {
  pending: PendingApprovalDeepLink;
  onClose: () => void;
}) {
  const client = useAuthenticatedClient();
  const region = useAuthStateValue((s) => s.cloudRegion);
  const ingressBaseUrl = agentIngressBaseUrl(pending.agent, region);

  const {
    data: approval,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["deep-link-approval", pending.agent, pending.requestId],
    queryFn: () =>
      ingressBaseUrl
        ? client.getAgentApprovalViaIngress(ingressBaseUrl, pending.requestId)
        : null,
    enabled: !!ingressBaseUrl,
    staleTime: 10_000,
  });

  const decide = useMutation<unknown, Error, DecideApprovalRequest>({
    mutationFn: (body) => {
      if (!ingressBaseUrl) {
        throw new Error(
          "Couldn't resolve the agent's ingress for your region.",
        );
      }
      return client.decideAgentApprovalViaIngress(
        ingressBaseUrl,
        pending.requestId,
        body,
      );
    },
    onSuccess: (_data, body) => {
      toast.success(body.decision === "approve" ? "Approved" : "Rejected", {
        description:
          body.decision === "approve"
            ? "Dispatched to the agent."
            : "The agent will see the rejection.",
      });
      onClose();
    },
    onError: (err) => {
      toast.error("Decision failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    },
  });

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onClose()}>
      <Dialog.Content maxWidth="520px">
        <Dialog.Title>
          <Flex align="center" gap="2">
            <LockKeyIcon size={16} className="text-(--amber-11)" />
            <Text className="font-semibold text-[14px]">Approval needed</Text>
          </Flex>
        </Dialog.Title>

        {isLoading ? (
          <Text className="text-[13px] text-gray-10">Loading approval…</Text>
        ) : isError || !approval ? (
          <Dialog.Description>
            <Text className="text-[13px] text-gray-11">
              Couldn't load this approval — it may have expired, already been
              decided, or belong to a session you don't own.
            </Text>
          </Dialog.Description>
        ) : (
          <Flex direction="column" gap="2">
            <Text className="font-medium font-mono text-[13px] text-gray-12">
              {approval.tool_name}
            </Text>
            <ArgsSection
              label="Proposed arguments"
              args={approval.proposed_args}
            />
            <AgentApprovalDecisionForm
              approval={approval}
              busy={decide.isPending}
              error={
                decide.isError
                  ? decide.error instanceof Error
                    ? decide.error.message
                    : "Decision failed"
                  : null
              }
              onSubmit={(body) => decide.mutate(body)}
            />
          </Flex>
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
