import {
  ArrowRightIcon,
  CaretRightIcon,
  ChatCircleIcon,
  GitPullRequestIcon,
  LightningIcon,
} from "@phosphor-icons/react";
import {
  deriveHeadline,
  humanizeReportTitle,
} from "@posthog/core/inbox/reportPresentation";
import { Button, cn, Text } from "@posthog/quill";
import type { Signal, SignalReport } from "@posthog/shared/types";
import {
  EMPTY_CHANNEL_REPORTS_FILTERS,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { ReportChartsSection } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { SignalReportActionabilityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportActionabilityBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useDiscussReport } from "@posthog/ui/features/inbox/hooks/useDiscussReport";
import { useInboxReportSignals } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import {
  navigateToChannel,
  navigateToReport,
} from "@posthog/ui/router/navigationBridge";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMemo, useState } from "react";

const RECENT_SHOWN = 5;
const SIGNALS_SHOWN = 6;

interface SpaceSignalsProps {
  channelId: string;
}

/**
 * What agents found in this space. Reports a scout or an agent assigned here,
 * split the way the space's Reports tab splits them: the ones that wait on a
 * person first, with their evidence and a way to act, then the stream.
 */
export function SpaceSignals({ channelId }: SpaceSignalsProps) {
  const view = useMemo(
    () => ({ kind: "channel" as const, channelId }),
    [channelId],
  );
  const { reports, sections, isLoading, isError } = useChannelReports(
    view,
    EMPTY_CHANNEL_REPORTS_FILTERS,
  );
  const recent = sections.rest.slice(0, RECENT_SHOWN);
  const signalTotal = reports.reduce((sum, r) => sum + r.signal_count, 0);
  const hasMore = sections.rest.length > RECENT_SHOWN;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          What agents found
          {reports.length > 0 ? (
            <span className="ml-1.5 font-normal tabular-nums">
              {sections.needsAttention.length > 0
                ? `${sections.needsAttention.length} need a decision · `
                : ""}
              {reports.length} {reports.length === 1 ? "report" : "reports"}
              {signalTotal > 0 ? ` · ${signalTotal} signals` : ""}
            </span>
          ) : null}
        </Text>
        {hasMore ? (
          <Button
            variant="link-muted"
            size="xs"
            onClick={() => navigateToChannel(channelId)}
          >
            All reports
            <ArrowRightIcon size={12} />
          </Button>
        ) : null}
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 py-3">
          <Spinner size="xs" aria-hidden="true" />
          <Text size="xxs" variant="muted">
            Loading reports
          </Text>
        </div>
      ) : isError ? (
        <Text size="xxs" variant="muted">
          Could not load the reports for this space.
        </Text>
      ) : reports.length === 0 ? (
        <div className="rounded-lg border border-border border-dashed px-4 py-4">
          <Text size="xs" variant="muted">
            Nothing yet. When a scout or an agent files a report about this
            area, it lands here with the signals behind it. Reports that wait on
            a decision come first.
          </Text>
        </div>
      ) : (
        <>
          {sections.needsAttention.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {sections.needsAttention.map((report) => (
                <li key={report.id}>
                  <DecisionCard report={report} channelId={channelId} />
                </li>
              ))}
            </ul>
          ) : null}
          {recent.length > 0 ? (
            <div className="flex flex-col gap-1">
              {sections.needsAttention.length > 0 ? (
                <Text size="xxs" variant="muted" className="mt-1 px-2">
                  Recent
                </Text>
              ) : null}
              <ul className="-mx-2 flex flex-col">
                {recent.map((report) => (
                  <li key={report.id}>
                    <ReportRow report={report} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/** A report that waits on a person: the evidence up front, and the two ways to act. */
function DecisionCard({
  report,
  channelId,
}: {
  report: SignalReport;
  channelId: string;
}) {
  const title = humanizeReportTitle(report.title, "Untitled report");
  const headline = deriveHeadline(report.summary);
  const hasSource = hasKnownSourceProduct(report.source_products);
  const { discussReport, isDiscussing } = useDiscussReport({
    report,
    channelId,
    surface: "list_row",
  });
  const firstChart = report.charts?.slice(0, 1);

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start gap-3">
        <PriorityMonogram priority={report.priority} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <button
            type="button"
            onClick={() => navigateToReport(report.id)}
            className="text-left font-medium text-foreground text-sm hover:underline"
          >
            {title}
          </button>
          {headline ? (
            <Text size="xs" variant="muted" className="line-clamp-3">
              {headline}
            </Text>
          ) : null}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-muted-foreground text-xxs">
            {report.actionability ? (
              <SignalReportActionabilityBadge
                actionability={report.actionability}
              />
            ) : null}
            {report.status !== "ready" ? (
              <SignalReportStatusBadge status={report.status} />
            ) : null}
            {report.signal_count > 0 ? (
              <span className="flex items-center gap-0.5 tabular-nums">
                <LightningIcon size={11} />
                {report.signal_count} signals
              </span>
            ) : null}
            {hasSource ? (
              <InboxMetaSourceStack sourceProducts={report.source_products} />
            ) : null}
            <RelativeTimestamp
              timestamp={report.updated_at ?? report.created_at}
            />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {report.implementation_pr_url ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                report.implementation_pr_url &&
                openExternalUrl(report.implementation_pr_url)
              }
            >
              <GitPullRequestIcon size={13} />
              PR
            </Button>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            disabled={isDiscussing}
            onClick={() => void discussReport()}
          >
            {isDiscussing ? <Spinner /> : <ChatCircleIcon size={13} />}
            Discuss
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => navigateToReport(report.id)}
          >
            Review
          </Button>
        </div>
      </div>
      {firstChart && firstChart.length > 0 ? (
        <ReportChartsSection reportId={report.id} charts={firstChart} />
      ) : null}
    </article>
  );
}

function ReportRow({ report }: { report: SignalReport }) {
  const [expanded, setExpanded] = useState(false);
  const title = humanizeReportTitle(report.title, "Untitled report");
  const headline = deriveHeadline(report.summary);
  const hasSource = hasKnownSourceProduct(report.source_products);
  const canExpand = report.signal_count > 0;

  return (
    <div className="rounded-md hover:bg-fill-hover">
      <div className="flex items-start gap-2 px-2 py-2">
        <button
          type="button"
          aria-label={expanded ? "Hide signals" : "Show signals"}
          aria-expanded={expanded}
          disabled={!canExpand}
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground",
            canExpand
              ? "hover:bg-fill-selected hover:text-foreground"
              : "opacity-0",
          )}
        >
          <CaretRightIcon
            size={12}
            className={cn("transition-transform", expanded && "rotate-90")}
          />
        </button>
        <PriorityMonogram priority={report.priority} />
        <button
          type="button"
          onClick={() => navigateToReport(report.id)}
          className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
        >
          <span className="truncate font-medium text-foreground text-xs">
            {title}
          </span>
          {headline ? (
            <span className="line-clamp-2 text-muted-foreground text-xxs">
              {headline}
            </span>
          ) : null}
        </button>
        <span className="flex shrink-0 items-center gap-2 text-muted-foreground text-xxs">
          {report.status !== "ready" ? (
            <SignalReportStatusBadge status={report.status} />
          ) : null}
          {report.signal_count > 0 ? (
            <span className="flex items-center gap-0.5 tabular-nums">
              <LightningIcon size={11} />
              {report.signal_count}
            </span>
          ) : null}
          {hasSource ? (
            <InboxMetaSourceStack sourceProducts={report.source_products} />
          ) : null}
          <RelativeTimestamp
            timestamp={report.updated_at ?? report.created_at}
          />
        </span>
      </div>
      {expanded ? <ReportSignals reportId={report.id} /> : null}
    </div>
  );
}

function ReportSignals({ reportId }: { reportId: string }) {
  const { data, isLoading } = useInboxReportSignals(reportId);
  const signals = data?.signals ?? [];
  return (
    <div className="mr-2 mb-2 ml-14 flex flex-col gap-1 border-border border-l pl-3">
      {isLoading ? (
        <div className="flex items-center gap-2 py-1">
          <Spinner size="xs" aria-hidden="true" />
          <Text size="xxs" variant="muted">
            Loading signals
          </Text>
        </div>
      ) : signals.length === 0 ? (
        <Text size="xxs" variant="muted">
          The signals behind this report are not available.
        </Text>
      ) : (
        <>
          {signals.slice(0, SIGNALS_SHOWN).map((signal) => (
            <SignalLine key={signal.signal_id} signal={signal} />
          ))}
          {signals.length > SIGNALS_SHOWN ? (
            <Button
              variant="link-muted"
              size="xs"
              className="self-start"
              onClick={() => navigateToReport(reportId)}
            >
              {signals.length - SIGNALS_SHOWN} more in the report
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}

function SignalLine({ signal }: { signal: Signal }) {
  return (
    <div className="flex items-start gap-2 py-0.5">
      <span className="mt-0.5 shrink-0">
        <InboxMetaSourceStack sourceProducts={[signal.source_product]} />
      </span>
      <span className="line-clamp-2 min-w-0 flex-1 text-foreground text-xxs">
        {signal.content}
      </span>
      <span className="shrink-0 text-muted-foreground text-xxs">
        <RelativeTimestamp timestamp={signal.timestamp} />
      </span>
    </div>
  );
}
