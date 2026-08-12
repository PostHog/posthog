import {
  ArrowSquareOutIcon,
  ChartLineIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import {
  BarChart,
  MetricCard,
  type Series,
  useChartTheme,
} from "@posthog/quill-charts";
import type {
  AgentAnalyticsData,
  AgentAnalyticsModelRow,
  AgentAnalyticsToolRow,
} from "@posthog/shared/agent-platform-types";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

const usd = (v: number): string =>
  v >= 100 ? `$${v.toFixed(0)}` : `$${v.toFixed(2)}`;
const pct = (v: number): string => `${(v * 100).toFixed(1)}%`;
const secs = (v: number): string => `${v.toFixed(v < 10 ? 1 : 0)}s`;
const int = (v: number): string => v.toLocaleString();

// Delta-pill label: magnitude only — MetricCard's arrow + colour carry the
// direction (sign of the change) and good/bad (`goodDirection`).
const pctDelta = (p: number): string => `${Math.abs(Math.round(p))}%`;
const ppDelta = (p: number): string => `${Math.abs(p).toFixed(1)}pp`;

// Compact uppercase tile label, matching the surrounding panes (MetricCard's
// own title styling is larger than this strip wants).
const tileTitle = (label: string): ReactNode => (
  <span className="text-[11px] text-gray-10 uppercase tracking-wide">
    {label}
  </span>
);

/**
 * The agent observability dashboard: top-line KPIs with 14-day spark trends +
 * WoW deltas plus charts. Pure presentation — `useAgentAnalytics` runs the
 * HogQL and shapes the data; this renders one of loading / error / empty /
 * populated.
 *
 * `scope` "overview" is the fleet board blended into the Fleet landing
 * (KPIs + spend-by-agent + cost-by-model; the agent list below carries the
 * per-agent breakdown). "agent" is the per-agent Observability tab (KPIs +
 * cost-by-model + tool reliability — spend-by-agent is meaningless for one).
 */
export function AgentAnalyticsView({
  data,
  title = "Observability",
  subtitle = "Last 7 days · 14-day trend",
  aiObservabilityUrl,
  isLoading,
  isError,
  errorMessage,
}: {
  data: AgentAnalyticsData | undefined;
  title?: string;
  subtitle?: string;
  /** Deep link into the team's AI observability product for trace-level depth. */
  aiObservabilityUrl?: string | null;
  isLoading?: boolean;
  isError?: boolean;
  errorMessage?: string | null;
}) {
  return (
    <Flex direction="column" gap="5">
      <Flex align="end" justify={title ? "between" : "end"} gap="3">
        {title ? (
          <Flex direction="column" gap="0.5">
            <Text className="font-semibold text-[15px] text-gray-12 leading-tight">
              {title}
            </Text>
            <Text className="text-[12px] text-gray-10">{subtitle}</Text>
          </Flex>
        ) : null}
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

      {isLoading && !data ? (
        <LoadingSkeleton />
      ) : isError ? (
        <ErrorState message={errorMessage} />
      ) : !data || data.empty ? (
        <EmptyState />
      ) : (
        <>
          <AgentAnalyticsKpiStrip data={data} />
          <Panel title="Cost by model">
            <CostByModelChart rows={data.byModel} />
          </Panel>
          <Panel title="Tool reliability">
            <ToolTable rows={data.toolErrors} />
          </Panel>
        </>
      )}
    </Flex>
  );
}

/**
 * The four top-line KPI tiles (spend / sessions / failure rate / p95) with
 * 14-day spark trends + WoW deltas. Reused standalone on the per-agent Overview
 * tab, where it owns its own loading / empty rendering.
 */
export function AgentAnalyticsKpiStrip({
  data,
  isLoading,
}: {
  data: AgentAnalyticsData | undefined;
  isLoading?: boolean;
}) {
  const theme = useChartTheme();
  if (isLoading && !data) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skel key={i} className="h-28" />
        ))}
      </div>
    );
  }
  if (!data || data.empty) {
    return <EmptyHint text="No AI activity in the last 7 days." />;
  }
  const { kpis, deltas, daily } = data;
  // Cost can come back negative from upstream LLM-observability cost calc (a
  // negative `$ai_total_cost_usd` on some generations). A negative aggregate
  // spend is never meaningful to show, so clamp the headline + sparkline to 0.
  const spendSeries = daily.spend.map((v) => Math.max(0, v));
  return (
    <Flex className="overflow-hidden rounded-(--radius-2) border border-border bg-(--color-panel-solid)">
      <KpiCell>
        <MetricCard
          title={tileTitle("Spend · 7d")}
          value={Math.max(0, kpis.spendUsd)}
          data={spendSeries}
          labels={daily.labels}
          theme={theme}
          formatValue={(v) => usd(Math.max(0, v))}
          change={deltas.spend != null ? { value: deltas.spend } : null}
          formatChange={pctDelta}
          goodDirection="down"
          sparklineHeight={28}
        />
      </KpiCell>
      <KpiCell>
        <MetricCard
          title={tileTitle("Sessions · 7d")}
          value={kpis.sessions}
          data={daily.sessions}
          labels={daily.labels}
          theme={theme}
          formatValue={int}
          change={deltas.sessions != null ? { value: deltas.sessions } : null}
          formatChange={pctDelta}
          goodDirection="up"
          sparklineHeight={28}
        />
      </KpiCell>
      <KpiCell>
        <MetricCard
          title={tileTitle("Failure rate · 7d")}
          value={kpis.failureRate}
          data={daily.failureRate}
          labels={daily.labels}
          theme={theme}
          formatValue={pct}
          change={
            deltas.failureRatePoints != null
              ? { value: deltas.failureRatePoints }
              : null
          }
          formatChange={ppDelta}
          goodDirection="down"
          sparklineHeight={28}
        />
      </KpiCell>
      <KpiCell last>
        <MetricCard
          title={tileTitle("p95 latency · 7d")}
          value={kpis.p95LatencyS}
          theme={theme}
          formatValue={secs}
          change={null}
          sparklineHeight={28}
        />
      </KpiCell>
    </Flex>
  );
}

/** One cell of the connected KPI strip: equal width with a divider between. */
function KpiCell({ children, last }: { children: ReactNode; last?: boolean }) {
  return (
    <div
      className={`min-w-0 flex-1 px-4 py-3 ${last ? "" : "border-(--gray-5) border-r"}`}
    >
      {children}
    </div>
  );
}

function CostByModelChart({ rows }: { rows: AgentAnalyticsModelRow[] }) {
  const theme = useChartTheme();
  if (rows.length === 0) {
    return <EmptyHint text="No model usage recorded yet." />;
  }
  const series: Series[] = [
    { key: "cost", label: "Cost (USD)", data: rows.map((r) => r.spendUsd) },
  ];
  return (
    // flex-col + fixed height: the quill BarChart sizes its canvas by filling a
    // flex-column parent (its root is `flex-1`); a plain block collapses the
    // canvas to height 0 and the chart renders blank.
    <div className="flex h-56 w-full flex-col">
      <BarChart
        series={series}
        labels={rows.map((r) => r.model)}
        config={{
          axisOrientation: "horizontal",
          showGrid: false,
          bars: { fitToHeight: true },
        }}
        theme={theme}
      />
    </div>
  );
}

function ToolTable({ rows }: { rows: AgentAnalyticsToolRow[] }) {
  if (rows.length === 0) {
    return <EmptyHint text="No tool calls recorded yet." />;
  }
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-(--gray-5) border-b text-left text-gray-10">
          <Th className="text-left">Tool</Th>
          <Th>Calls</Th>
          <Th>Errors</Th>
          <Th>Error rate</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.tool} className="border-(--gray-4) border-b last:border-0">
            <td className="py-1.5 pr-2 font-mono text-gray-12">{r.tool}</td>
            <Td>{int(r.calls)}</Td>
            <Td>{int(r.errors)}</Td>
            <Td>
              <span
                className={r.errorRate > 0 ? "text-(--red-11)" : "text-gray-12"}
              >
                {pct(r.errorRate)}
              </span>
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-(--radius-2) border border-border bg-(--color-panel-solid)">
      <div className="border-(--gray-5) border-b px-3 py-2">
        <Text className="font-medium text-[11px] text-gray-10 uppercase tracking-wide">
          {title}
        </Text>
      </div>
      <div className="px-3 py-3">{children}</div>
    </div>
  );
}

function Th({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <th className={`py-1.5 pr-2 font-medium ${className ?? "text-right"}`}>
      {children}
    </th>
  );
}

function Td({ children }: { children: ReactNode }) {
  return (
    <td className="py-1.5 pr-2 text-right text-gray-12 tabular-nums">
      {children}
    </td>
  );
}

function EmptyHint({ text }: { text: string }) {
  return <Text className="text-[12px] text-gray-10 italic">{text}</Text>;
}

function EmptyState() {
  return (
    <Flex
      direction="column"
      align="center"
      gap="2"
      className="rounded-(--radius-2) border border-(--gray-5) border-dashed py-16 text-center"
    >
      <ChartLineIcon size={24} className="text-gray-9" />
      <Text className="font-medium text-[13px] text-gray-12">
        No AI activity yet
      </Text>
      <Text className="max-w-sm text-[12px] text-gray-11 leading-snug">
        Once your agents run, their model calls, tool spans, cost and latency
        show up here — and in full detail in AI observability.
      </Text>
    </Flex>
  );
}

function ErrorState({ message }: { message?: string | null }) {
  return (
    <Flex
      direction="column"
      align="center"
      gap="2"
      className="rounded-(--radius-2) border border-(--red-6) border-dashed py-16 text-center"
    >
      <WarningIcon size={24} className="text-(--red-11)" />
      <Text className="font-medium text-[13px] text-gray-12">
        Couldn't load analytics
      </Text>
      <Text className="max-w-md text-[12px] text-gray-11 leading-snug">
        {message ?? "The query endpoint returned an error."}
      </Text>
    </Flex>
  );
}

function LoadingSkeleton() {
  return (
    <Flex direction="column" gap="5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skel key={i} className="h-20" />
        ))}
      </div>
      <Skel className="h-64" />
      <Skel className="h-32" />
    </Flex>
  );
}

function Skel({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2) ${className ?? ""}`}
    />
  );
}
