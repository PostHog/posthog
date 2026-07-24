import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  LockKeyIcon,
  MagnifyingGlassIcon,
  RobotIcon,
} from "@phosphor-icons/react";
import type {
  AgentAnalyticsAgentRow,
  AgentApplication,
} from "@posthog/shared/agent-platform-types";
import { AgentsTabLayout } from "@posthog/ui/features/agents/components/AgentsTabLayout";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Button } from "@posthog/ui/primitives/Button";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useAuthStateValue } from "../../auth/store";
import { useAgentAnalytics } from "../hooks/useAgentAnalytics";
import { useAgentApplications } from "../hooks/useAgentApplications";
import { useAgentFleetApprovals } from "../hooks/useAgentFleetApprovals";
import { formatSpendUsd } from "../utils/format";
import { aiObservabilityTracesUrl } from "../utils/observabilityLinks";
import { AgentAnalyticsKpiStrip } from "./AgentAnalyticsView";
import { AgentDetailEmptyState } from "./AgentDetailLayout";
import { AgentFleetLiveSessionsPanel } from "./AgentFleetLiveSessionsPanel";

type StatusFilter = "all" | "live" | "drafts";

/** Agents per page in the fleet list. */
const PAGE_SIZE = 8;

/**
 * The Fleet tab. Renders the deployed-agent fleet as the primary
 * surface: a searchable, status-filtered, paged list with the 7-day activity
 * strip pinned at the top and operational / live-now panels below.
 */
export function AgentApplicationsListView() {
  const region = useAuthStateValue((s) => s.cloudRegion);
  const projectId = useAuthStateValue((s) => s.currentProjectId);

  const {
    data: applications,
    isLoading,
    isError,
    error,
  } = useAgentApplications();
  const { data: analytics, isLoading: analyticsLoading } = useAgentAnalytics();
  const { data: queuedApprovals } = useAgentFleetApprovals({ state: "queued" });
  const aiObservabilityUrl = aiObservabilityTracesUrl(region, projectId);
  const pendingCount = queuedApprovals?.length ?? 0;
  const hasAnalytics = analytics ? !analytics.empty : false;

  // Index the per-agent rollups by application id so each row can show its own
  // sessions / spend / failure rate without a second request.
  const statsById = useMemo(() => {
    const map = new Map<string, AgentAnalyticsAgentRow>();
    for (const row of analytics?.byAgent ?? []) {
      map.set(row.id, row);
    }
    return map;
  }, [analytics]);

  // Live agents sort ahead of drafts so the operational view foregrounds what's
  // serving traffic. Search + status filter + paging keep a large fleet
  // navigable.
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);

  const allApps = useMemo(() => applications ?? [], [applications]);
  const liveCount = useMemo(
    () => allApps.filter((a) => a.live_revision != null).length,
    [allApps],
  );
  const draftCount = allApps.length - liveCount;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allApps
      .filter((app) => {
        if (status === "live" && app.live_revision == null) return false;
        if (status === "drafts" && app.live_revision != null) return false;
        if (!q) return true;
        return (
          app.name.toLowerCase().includes(q) ||
          (app.slug?.toLowerCase().includes(q) ?? false) ||
          (app.description?.toLowerCase().includes(q) ?? false)
        );
      })
      .sort(
        (a, b) =>
          Number(b.live_revision != null) - Number(a.live_revision != null),
      );
  }, [allApps, status, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = filtered.slice(
    safePage * PAGE_SIZE,
    safePage * PAGE_SIZE + PAGE_SIZE,
  );

  function changeStatus(next: StatusFilter) {
    setStatus(next);
    setPage(0);
  }

  function changeQuery(next: string) {
    setQuery(next);
    setPage(0);
  }

  const statusFilters: { id: StatusFilter; label: string; count: number }[] = [
    { id: "all", label: "All", count: allApps.length },
    { id: "live", label: "Live", count: liveCount },
    { id: "drafts", label: "Drafts", count: draftCount },
  ];

  return (
    <AgentsTabLayout activeTab="applications">
      <Flex direction="column" gap="6">
        {hasAnalytics ? (
          <section>
            <Flex align="center" justify="between" gap="3" className="mb-3">
              <Text className="font-semibold text-[13px] text-gray-12">
                Activity · last 7 days
              </Text>
              {aiObservabilityUrl ? (
                <button
                  type="button"
                  onClick={() => openExternalUrl(aiObservabilityUrl)}
                  className="inline-flex shrink-0 items-center gap-1 text-[12px] text-gray-11 no-underline hover:text-gray-12"
                >
                  Open in AI observability
                  <ArrowSquareOutIcon size={12} />
                </button>
              ) : null}
            </Flex>
            <AgentAnalyticsKpiStrip
              data={analytics}
              isLoading={analyticsLoading}
            />
          </section>
        ) : null}

        <section>
          {isLoading ? (
            <ApplicationsSkeleton />
          ) : isError ? (
            <AgentDetailEmptyState
              title="Couldn't load applications"
              description={
                error instanceof Error
                  ? error.message
                  : "The agent platform API returned an error."
              }
            />
          ) : allApps.length === 0 ? (
            <AgentDetailEmptyState
              title="No agents yet"
              description="Deployed agents on the agent platform will show up here."
            />
          ) : (
            <Flex direction="column" gap="3">
              <Flex align="center" justify="between" gap="3" wrap="wrap">
                <div className="relative min-w-0 flex-1 sm:max-w-xs">
                  <MagnifyingGlassIcon
                    size={13}
                    className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-gray-10"
                  />
                  <input
                    type="search"
                    value={query}
                    onChange={(e) => changeQuery(e.currentTarget.value)}
                    placeholder="Search agents…"
                    aria-label="Search agents"
                    className="h-8 w-full rounded-(--radius-2) border border-border bg-(--color-panel-solid) pr-2 pl-8 text-[12.5px]"
                  />
                </div>
                <Flex gap="2" wrap="wrap" className="shrink-0">
                  {statusFilters.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => changeStatus(f.id)}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] ${
                        status === f.id
                          ? "border-(--accent-7) bg-(--accent-3) text-gray-12"
                          : "border-border text-gray-11 hover:border-(--gray-7)"
                      }`}
                    >
                      {f.label}
                      <span className="text-[11px] text-gray-10 tabular-nums">
                        {f.count}
                      </span>
                    </button>
                  ))}
                </Flex>
              </Flex>

              {pageItems.length === 0 ? (
                <AgentDetailEmptyState
                  title="No matching agents"
                  description="No agents match your search and filters."
                />
              ) : (
                <Flex direction="column" gap="2">
                  {pageItems.map((app) => (
                    <ApplicationRow
                      key={app.id}
                      application={app}
                      stats={statsById.get(app.id)}
                    />
                  ))}
                </Flex>
              )}

              {filtered.length > 0 ? (
                <Flex
                  align="center"
                  justify="between"
                  gap="3"
                  wrap="wrap"
                  className="pt-1"
                >
                  <Text className="text-[11px] text-gray-10 tabular-nums">
                    Showing {safePage * PAGE_SIZE + 1}–
                    {safePage * PAGE_SIZE + pageItems.length} of{" "}
                    {filtered.length}
                  </Text>
                  {pageCount > 1 ? (
                    <Flex align="center" gap="2">
                      <Button
                        variant="soft"
                        size="1"
                        disabled={safePage === 0}
                        onClick={() => setPage((p) => Math.max(0, p - 1))}
                      >
                        Previous
                      </Button>
                      <Text className="text-[11px] text-gray-10 tabular-nums">
                        {safePage + 1} / {pageCount}
                      </Text>
                      <Button
                        variant="soft"
                        size="1"
                        disabled={safePage >= pageCount - 1}
                        onClick={() =>
                          setPage((p) => Math.min(pageCount - 1, p + 1))
                        }
                      >
                        Next
                      </Button>
                    </Flex>
                  ) : null}
                </Flex>
              ) : null}
            </Flex>
          )}
        </section>

        <OperationalStrip pendingCount={pendingCount} />

        <AgentFleetLiveSessionsPanel />
      </Flex>
    </AgentsTabLayout>
  );
}

function ApplicationRow({
  application,
  stats,
}: {
  application: AgentApplication;
  stats?: AgentAnalyticsAgentRow;
}) {
  const isLive = application.live_revision != null;
  return (
    <Link
      to="/code/agents/applications/$idOrSlug"
      params={{ idOrSlug: application.slug ?? application.id }}
      className="flex items-center justify-between gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 no-underline transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2)"
    >
      <Flex align="center" gap="3" className="min-w-0">
        <RobotIcon size={20} className="shrink-0 text-gray-11" />
        <Flex direction="column" gap="0.5" className="min-w-0">
          <Flex align="center" gap="2" className="min-w-0">
            <Text className="truncate font-medium text-[13px] text-gray-12">
              {application.name}
            </Text>
            <Badge color={isLive ? "green" : "gray"}>
              {isLive ? "Live" : "Draft"}
            </Badge>
          </Flex>
          <Text className="truncate text-[12px] text-gray-11 leading-snug">
            {application.description?.trim()
              ? application.description
              : (application.slug ?? application.id)}
          </Text>
        </Flex>
      </Flex>
      <Flex align="center" gap="4" className="shrink-0">
        {stats ? <RowStats stats={stats} /> : null}
        <CaretRightIcon size={14} className="shrink-0 text-gray-10" />
      </Flex>
    </Link>
  );
}

/** Inline 7-day rollups shown on an agent row, joined from the fleet query. */
function RowStats({ stats }: { stats: AgentAnalyticsAgentRow }) {
  return (
    <Flex align="center" gap="4" className="hidden sm:flex">
      <RowStat label="Sessions" value={stats.sessions.toLocaleString()} />
      <RowStat label="Spend" value={formatSpendUsd(stats.spendUsd)} />
      <RowStat
        label="Fail rate"
        value={`${(stats.failureRate * 100).toFixed(1)}%`}
        attention={stats.failureRate > 0}
      />
    </Flex>
  );
}

function RowStat({
  label,
  value,
  attention,
}: {
  label: string;
  value: string;
  attention?: boolean;
}) {
  return (
    <Flex direction="column" align="end" gap="0.5" className="shrink-0">
      <Text
        className={`font-medium text-[12px] tabular-nums ${
          attention ? "text-(--red-11)" : "text-gray-12"
        }`}
      >
        {value}
      </Text>
      <Text className="text-[10px] text-gray-10 uppercase tracking-wide">
        {label}
      </Text>
    </Flex>
  );
}

/**
 * Operational counts strip — always renders the pending-approvals count as a
 * deep link to the fleet approvals queue, and visually emphasizes the row when
 * `pendingCount > 0`.
 */
function OperationalStrip({ pendingCount }: { pendingCount: number }) {
  const pendingAttention = pendingCount > 0;
  return (
    <Flex align="center" gap="5" className="text-[12.5px]">
      <Link
        to="/code/agents/applications/approvals"
        className="inline-flex items-center gap-1 text-gray-11 no-underline hover:text-gray-12"
      >
        <LockKeyIcon
          size={13}
          className={`mr-1 ${pendingAttention ? "text-(--amber-11)" : "text-gray-10"}`}
        />
        <Text
          className={`font-medium tabular-nums ${pendingAttention ? "text-(--amber-11)" : "text-gray-12"}`}
        >
          {pendingCount}
        </Text>
        <Text>pending approval{pendingCount === 1 ? "" : "s"}</Text>
        <CaretRightIcon size={11} className="text-gray-10" />
      </Link>
    </Flex>
  );
}

function ApplicationsSkeleton() {
  return (
    <Flex direction="column" gap="2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-[58px] animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)"
        />
      ))}
    </Flex>
  );
}
