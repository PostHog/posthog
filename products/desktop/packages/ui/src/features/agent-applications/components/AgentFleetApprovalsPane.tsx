import { ArrowLeftIcon, LockKeyIcon, RobotIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import type {
  AgentApplication,
  AgentApprovalRequest,
} from "@posthog/shared/agent-platform-types";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useMemo } from "react";
import { useSetAgentBuilderPage } from "../agent-builder/useSetAgentBuilderPage";
import { useAgentApplications } from "../hooks/useAgentApplications";
import { useAgentFleetApprovals } from "../hooks/useAgentFleetApprovals";
import { approvalStateColor, approvalStateLabel } from "../utils/format";
import { AgentApprovalDetail } from "./AgentApprovalDetail";
import { AgentDetailEmptyState } from "./AgentDetailLayout";
import { APPROVAL_FILTERS, type ApprovalFilter } from "./agentApprovalsFilters";
import { RefreshIndicator } from "./RefreshIndicator";

/**
 * Fleet-wide approvals queue: a master/detail mirror of the per-agent
 * `AgentApprovalsPane` but cross-agent. Each row shows the agent it belongs to
 * (joined client-side with `useAgentApplications`) and the detail pane reuses
 * `AgentApprovalDetail` once we resolve the application's `idOrSlug`. Owns its
 * own chrome (back link + title) rather than nesting under the Scouts /
 * Fleet tab bar, matching how per-agent detail pages render.
 */
export function AgentFleetApprovalsPane({
  selectedId,
  onSelect,
  filter,
  onFilterChange,
}: {
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
  } = useAgentFleetApprovals(filter === "all" ? undefined : { state: filter });
  const { data: applications } = useAgentApplications();

  const approvals = useMemo(() => data ?? [], [data]);
  const appsById = useMemo(() => {
    const map = new Map<string, AgentApplication>();
    for (const app of applications ?? []) {
      map.set(app.id, app);
    }
    return map;
  }, [applications]);

  const selected = selectedId
    ? (approvals.find((a) => a.id === selectedId) ?? null)
    : null;
  const selectedApp = selected ? appsById.get(selected.application_id) : null;
  const selectedIdOrSlug = selectedApp?.slug ?? selectedApp?.id ?? null;

  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <LockKeyIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Fleet approvals"
        >
          Fleet approvals
        </Text>
      </Flex>
    ),
    [],
  );
  useSetHeaderContent(headerContent);
  useSetAgentBuilderPage({ kind: "agent-list" });

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
    <AgentDetailEmptyState
      title="You need organization admin access"
      description="Tool approvals can only be viewed and decided by organization admins. Ask an admin to review pending requests."
    />
  ) : isError ? (
    <AgentDetailEmptyState
      title="Couldn't load approvals"
      description="The agent platform API returned an error while loading fleet approvals. Try again shortly."
    />
  ) : approvals.length === 0 ? (
    <AgentDetailEmptyState
      title="Nothing here"
      description={
        filter === "queued"
          ? "No tool calls are waiting for a decision across the fleet."
          : "No approval requests match this filter."
      }
    />
  ) : (
    <Flex direction="column" gap="2">
      {approvals.map((approval) => (
        <FleetApprovalRow
          key={approval.id}
          approval={approval}
          application={appsById.get(approval.application_id)}
          selected={approval.id === selectedId}
          onSelect={() => onSelect(approval.id)}
        />
      ))}
    </Flex>
  );

  return (
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="3"
        className="shrink-0 cursor-default select-none border-(--gray-5) border-b px-6 pt-5"
      >
        <Link
          to="/code/agents/applications"
          className="flex w-fit items-center gap-1.5 text-[12px] text-gray-11 no-underline hover:text-gray-12"
        >
          <ArrowLeftIcon size={13} />
          Fleet
        </Link>
        <Flex align="center" gap="2" wrap="wrap">
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Fleet approvals
          </Text>
        </Flex>
        <Text className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
          Tool calls across every deployed agent that are waiting on (or have
          received) a human decision.
        </Text>
      </Flex>

      <Flex direction="column" className="min-h-0 flex-1">
        <div className="shrink-0 px-5 pt-5 pb-3">{filters}</div>
        {selected && selectedIdOrSlug ? (
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(300px,380px)_minmax(0,1fr)] divide-x divide-(--gray-5) overflow-hidden border-(--gray-5) border-t">
            <aside className="min-h-0 overflow-y-auto px-3 py-3">{list}</aside>
            <main className="min-h-0 overflow-hidden">
              <AgentApprovalDetail
                idOrSlug={selectedIdOrSlug}
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
    </Flex>
  );
}

function FleetApprovalRow({
  approval,
  application,
  selected,
  onSelect,
}: {
  approval: AgentApprovalRequest;
  application: AgentApplication | undefined;
  selected: boolean;
  onSelect: () => void;
}) {
  const isQueued = approval.state === "queued";
  const agentLabel =
    application?.name ?? application?.slug ?? approval.application_id;
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
      <Flex direction="column" gap="1" className="min-w-0 flex-1">
        <Flex align="center" gap="2" className="min-w-0">
          <Badge color={approvalStateColor(approval.state)}>
            {approvalStateLabel(approval.state)}
          </Badge>
          <Text className="truncate font-medium text-[12.5px] text-gray-12 [font-family:var(--font-mono)]">
            {approval.tool_name}
          </Text>
        </Flex>
        <Flex align="center" gap="1.5" className="min-w-0">
          <RobotIcon size={11} className="shrink-0 text-gray-10" />
          <Text className="truncate text-[11px] text-gray-11">
            {agentLabel}
          </Text>
        </Flex>
      </Flex>
      <Text className="shrink-0 text-[11px] text-gray-10">
        {isQueued
          ? `expires ${formatRelativeTimeShort(approval.expires_at)}`
          : formatRelativeTimeShort(approval.created_at)}
      </Text>
    </button>
  );
}
