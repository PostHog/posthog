import {
  CheckCircleIcon,
  LockKeyIcon,
  WarningIcon,
  XCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { AgentApprovalRequest } from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { Flex, IconButton, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useDecideAgentApproval } from "../hooks/useDecideAgentApproval";
import { approvalStateColor, approvalStateLabel } from "../utils/format";
import { AgentApprovalDecisionForm } from "./AgentApprovalDecisionForm";
import { AgentSessionDetailBody } from "./AgentSessionDetailBody";

type Pane = "approval" | "session";

/**
 * Master-detail panel for a single approval. The **Approval** tab carries the
 * proposed args + decision controls; the **Session** tab embeds the agent run
 * that proposed the gated call (via {@link AgentSessionDetailBody}) so the
 * approver can read the full context that led to it.
 */
export function AgentApprovalDetail({
  idOrSlug,
  approval,
  onClose,
}: {
  idOrSlug: string;
  approval: AgentApprovalRequest;
  onClose: () => void;
}) {
  const [pane, setPane] = useState<Pane>("approval");
  const isQueued = approval.state === "queued";

  return (
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="3"
        className="shrink-0 border-(--gray-5) border-b px-5 pt-4"
      >
        <Flex align="start" justify="between" gap="3">
          <Flex direction="column" gap="1" className="min-w-0">
            <Flex align="center" gap="2" className="min-w-0">
              <LockKeyIcon size={14} className="shrink-0 text-gray-10" />
              <Text className="truncate font-semibold text-[14px] text-gray-12 [font-family:var(--font-mono)]">
                {approval.tool_name}
              </Text>
              <Badge color={approvalStateColor(approval.state)}>
                {approvalStateLabel(approval.state)}
              </Badge>
            </Flex>
            <Text className="text-[11px] text-gray-10">
              {isQueued
                ? `expires ${formatRelativeTimeShort(approval.expires_at)}`
                : `created ${formatRelativeTimeShort(approval.created_at)}`}
            </Text>
          </Flex>
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            onClick={onClose}
            aria-label="Close approval"
          >
            <XIcon size={15} />
          </IconButton>
        </Flex>

        <Flex gap="1" className="-mb-px">
          {(["approval", "session"] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPane(p)}
              className={`border-b-2 px-3 pb-2.5 text-[12.5px] capitalize ${
                p === pane
                  ? "border-(--accent-9) font-medium text-gray-12"
                  : "border-transparent text-gray-11 hover:text-gray-12"
              }`}
            >
              {p}
            </button>
          ))}
        </Flex>
      </Flex>

      {pane === "approval" ? (
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <ArgsSection
            label="Proposed arguments"
            args={approval.proposed_args}
          />
          {isQueued ? (
            <DecisionForm idOrSlug={idOrSlug} approval={approval} />
          ) : (
            <DecidedOutcome approval={approval} />
          )}
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          <AgentSessionDetailBody
            idOrSlug={idOrSlug}
            sessionId={approval.session_id}
          />
        </div>
      )}
    </Flex>
  );
}

function DecisionForm({
  idOrSlug,
  approval,
}: {
  idOrSlug: string;
  approval: AgentApprovalRequest;
}) {
  const decide = useDecideAgentApproval(idOrSlug);
  return (
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
      onSubmit={(body) => decide.mutate({ approvalId: approval.id, body })}
    />
  );
}

function DecidedOutcome({ approval }: { approval: AgentApprovalRequest }) {
  const dispatchError =
    approval.dispatch_outcome &&
    typeof approval.dispatch_outcome === "object" &&
    "error" in approval.dispatch_outcome
      ? String(approval.dispatch_outcome.error)
      : null;
  const banner = outcomeBanner(approval.state, !!dispatchError);

  return (
    <Flex direction="column" gap="3" className="mt-4">
      <Flex
        align="center"
        gap="2"
        className={`rounded-(--radius-2) border px-3 py-2 ${banner.classes}`}
      >
        <banner.Icon size={16} weight="fill" className={banner.iconClass} />
        <Flex direction="column" gap="0.5" className="min-w-0">
          <Text className="font-medium text-[12.5px] text-gray-12">
            {banner.title}
          </Text>
          {approval.decision_at ? (
            <Text className="text-[11px] text-gray-11">
              {formatRelativeTimeShort(approval.decision_at)}
              {approval.decision_by ? ` by ${approval.decision_by}` : ""}
            </Text>
          ) : null}
        </Flex>
      </Flex>
      {approval.decision_reason ? (
        <Text className="text-[12px] text-gray-11">
          Reason: {approval.decision_reason}
        </Text>
      ) : null}
      {approval.decided_args ? (
        <ArgsSection label="Edited arguments" args={approval.decided_args} />
      ) : null}
      {dispatchError ? (
        <Text className="text-(--red-11) text-[12px]">
          Dispatch error: {dispatchError}
        </Text>
      ) : null}
    </Flex>
  );
}

function outcomeBanner(
  state: AgentApprovalRequest["state"],
  hasDispatchError: boolean,
): {
  title: string;
  classes: string;
  Icon: typeof CheckCircleIcon;
  iconClass: string;
} {
  if (hasDispatchError || state === "dispatched_failed") {
    return {
      title: "Approved, but dispatch failed",
      classes: "border-(--red-6) bg-(--red-2)",
      Icon: WarningIcon,
      iconClass: "text-(--red-11)",
    };
  }
  if (state === "rejected") {
    return {
      title: "Rejected",
      classes: "border-(--gray-6) bg-(--gray-2)",
      Icon: XCircleIcon,
      iconClass: "text-gray-11",
    };
  }
  if (state === "expired") {
    return {
      title: "Expired before a decision",
      classes: "border-(--amber-6) bg-(--amber-2)",
      Icon: WarningIcon,
      iconClass: "text-(--amber-11)",
    };
  }
  return {
    title: "Approved & dispatched",
    classes: "border-(--green-6) bg-(--green-2)",
    Icon: CheckCircleIcon,
    iconClass: "text-(--green-11)",
  };
}

export function ArgsSection({
  label,
  args,
}: {
  label: string;
  args: Record<string, unknown>;
}) {
  const isEmpty = !args || Object.keys(args).length === 0;
  return (
    <Flex direction="column" gap="1.5">
      <Text className="text-[11px] text-gray-10 uppercase tracking-wide">
        {label}
      </Text>
      {isEmpty ? (
        <Text className="text-[12px] text-gray-10">No arguments</Text>
      ) : (
        <CodeBlock>{JSON.stringify(args, null, 2)}</CodeBlock>
      )}
    </Flex>
  );
}
