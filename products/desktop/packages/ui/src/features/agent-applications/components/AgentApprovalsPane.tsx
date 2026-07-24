import { LockKeyIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { AgentApprovalRequest } from "@posthog/shared/agent-platform-types";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { useMemo } from "react";
import { useAgentApplicationApprovals } from "../hooks/useAgentApplicationApprovals";
import { approvalStateColor, approvalStateLabel } from "../utils/format";
import { AgentApprovalDetail } from "./AgentApprovalDetail";
import { AgentDetailEmptyState, AgentDetailLayout } from "./AgentDetailLayout";
import { APPROVAL_FILTERS, type ApprovalFilter } from "./agentApprovalsFilters";
import { RefreshIndicator } from "./RefreshIndicator";

export type { ApprovalFilter };

/**
 * Per-agent Approvals pane, master-detail: a filterable list on the left and,
 * when a row is selected (URL `?request=<id>`), an {@link AgentApprovalDetail}
 * panel on the right with the proposed args, decision controls, and the
 * embedded session that proposed the gated call.
 */
export function AgentApprovalsPane({
  idOrSlug,
  selectedId,
  onSelect,
  filter,
  onFilterChange,
}: {
  idOrSlug: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  filter: ApprovalFilter;
  onFilterChange: (f: ApprovalFilter) => void;
}) {
  const {
    data,
    isLoading,
    isError,
    isPermissionError,
    isFetching,
    dataUpdatedAt,
    refetch,
  } = useAgentApplicationApprovals(
    idOrSlug,
    filter === "all" ? undefined : { state: filter },
  );
  const approvals = useMemo(() => data ?? [], [data]);
  const selected = selectedId
    ? (approvals.find((a) => a.id === selectedId) ?? null)
    : null;

  const filters = (
    <Flex align="center" justify="between" gap="3" wrap="wrap">
      <Flex gap="2" wrap="wrap" className="min-w-0">
        {APPROVAL_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => onFilterChange(f.id)}
            className={`rounded-full border px-3 py-1 text-[12px] ${
              filter === f.id
                ? "border-(--accent-7) bg-(--accent-3) text-gray-12"
                : "border-border text-gray-11 hover:border-(--gray-7)"
            }`}
          >
            {f.label}
          </button>
        ))}
      </Flex>
      <RefreshIndicator
        updatedAt={dataUpdatedAt}
        isFetching={isFetching}
        onRefresh={() => void refetch()}
        compact={!!selectedId}
      />
    </Flex>
  );

  const list = isLoading ? (
    <Flex direction="column" gap="2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[60px] animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
        />
      ))}
    </Flex>
  ) : isPermissionError ? (
    // A 404 here means the admin gate: AgentDetailLayout only renders this
    // pane's content once the application itself has loaded successfully.
    <AgentDetailEmptyState
      title="You need organization admin access"
      description="Tool approvals can only be viewed and decided by organization admins. Ask an admin to review pending requests."
    />
  ) : isError ? (
    <AgentDetailEmptyState
      title="Couldn't load approvals"
      description="The agent platform API returned an error while loading approvals. Try again shortly."
    />
  ) : approvals.length === 0 ? (
    <AgentDetailEmptyState
      title="Nothing here"
      description={
        filter === "queued"
          ? "No tool calls are waiting for a decision."
          : "No approval requests match this filter."
      }
    />
  ) : (
    <Flex direction="column" gap="2">
      {approvals.map((approval) => (
        <ApprovalRow
          key={approval.id}
          approval={approval}
          selected={approval.id === selectedId}
          onSelect={() => onSelect(approval.id)}
        />
      ))}
    </Flex>
  );

  return (
    <AgentDetailLayout idOrSlug={idOrSlug} activeTab="approvals" fill>
      <Flex direction="column" className="h-full min-h-0">
        <div className="shrink-0 px-5 pt-5 pb-3">{filters}</div>
        {selected ? (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(300px,380px)_minmax(0,1fr)] divide-x divide-(--gray-5) overflow-hidden border-(--gray-5) border-t">
            <aside className="min-h-0 overflow-y-auto px-3 py-3">{list}</aside>
            <main className="min-h-0 overflow-hidden">
              <AgentApprovalDetail
                idOrSlug={idOrSlug}
                approval={selected}
                onClose={() => onSelect(null)}
              />
            </main>
          </div>
        ) : (
          <div className="min-h-0 flex-1 overflow-auto">
            <div className="mx-auto max-w-4xl px-5 pb-6">{list}</div>
          </div>
        )}
      </Flex>
    </AgentDetailLayout>
  );
}

function ApprovalRow({
  approval,
  selected,
  onSelect,
}: {
  approval: AgentApprovalRequest;
  selected: boolean;
  onSelect: () => void;
}) {
  const isQueued = approval.state === "queued";
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full items-center gap-3 rounded-(--radius-2) border px-4 py-3 text-left ${
        selected
          ? "border-(--accent-7) bg-(--accent-3)"
          : "border-border bg-(--color-panel-solid) hover:border-(--gray-7)"
      }`}
    >
      <LockKeyIcon size={13} className="shrink-0 text-gray-10" />
      <Flex direction="column" gap="1" className="min-w-0 flex-1">
        <Flex align="center" gap="2" className="min-w-0">
          <Badge color={approvalStateColor(approval.state)}>
            {approvalStateLabel(approval.state)}
          </Badge>
          <Text className="truncate font-medium text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
            {approval.tool_name}
          </Text>
        </Flex>
        <Text className="truncate text-[11px] text-gray-10">
          {summarizeArgs(approval.proposed_args)}
        </Text>
      </Flex>
      <Text className="shrink-0 text-[11px] text-gray-10">
        {isQueued
          ? `expires ${formatRelativeTimeShort(approval.expires_at)}`
          : formatRelativeTimeShort(approval.created_at)}
      </Text>
    </button>
  );
}

function summarizeArgs(args: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return "No arguments";
  const compact = JSON.stringify(args);
  return compact.length > 140 ? `${compact.slice(0, 140)}…` : compact;
}
