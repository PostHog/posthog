import {
  ArrowRightIcon,
  CaretRightIcon,
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
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useInboxReportSignals } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import {
  navigateToChannel,
  navigateToReport,
} from "@posthog/ui/router/navigationBridge";
import { useMemo, useState } from "react";

const SHOWN = 5;
const SIGNALS_SHOWN = 6;

interface SpaceSignalsProps {
  channelId: string;
}

/**
 * What agents found in this space: the reports a scout or an agent assigned
 * here, newest first, each one openable to the signals behind it. This puts
 * the facts next to the goals instead of only what a person wrote down.
 */
export function SpaceSignals({ channelId }: SpaceSignalsProps) {
  const view = useMemo(
    () => ({ kind: "channel" as const, channelId }),
    [channelId],
  );
  const { reports, isLoading, isError } = useChannelReports(
    view,
    EMPTY_CHANNEL_REPORTS_FILTERS,
  );
  const shown = reports.slice(0, SHOWN);
  const signalTotal = reports.reduce((sum, r) => sum + r.signal_count, 0);

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          What agents found
          {reports.length > 0 ? (
            <span className="ml-1.5 tabular-nums">
              {reports.length} {reports.length === 1 ? "report" : "reports"}
              {signalTotal > 0 ? ` · ${signalTotal} signals` : ""}
            </span>
          ) : null}
        </Text>
        {reports.length > SHOWN ? (
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
      ) : shown.length === 0 ? (
        <div className="rounded-lg border border-border border-dashed px-4 py-4">
          <Text size="xs" variant="muted">
            No reports assigned to this space yet. When a scout or an agent
            files a report about this area, it shows here with the signals
            behind it.
          </Text>
        </div>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {shown.map((report) => (
            <li key={report.id}>
              <ReportRow report={report} />
            </li>
          ))}
        </ul>
      )}
    </section>
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
