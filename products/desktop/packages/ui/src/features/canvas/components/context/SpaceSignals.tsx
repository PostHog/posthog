import { ArrowRightIcon } from "@phosphor-icons/react";
import {
  deriveHeadline,
  humanizeReportTitle,
} from "@posthog/core/inbox/reportPresentation";
import { Button, Text } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import {
  EMPTY_CHANNEL_REPORTS_FILTERS,
  useChannelReports,
} from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import {
  navigateToChannel,
  navigateToReport,
} from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";

const SHOWN = 5;

interface SpaceSignalsProps {
  channelId: string;
}

/**
 * What agents found in this space: the newest reports filed here, so the
 * context page shows facts next to the goals instead of only what a person
 * wrote down.
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

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          What agents found
        </Text>
        {reports.length > SHOWN ? (
          <Button
            variant="link-muted"
            size="xs"
            onClick={() => navigateToChannel(channelId)}
          >
            All {reports.length} reports
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
            No reports yet. When agents find something in this space, the newest
            findings show here.
          </Text>
        </div>
      ) : (
        <ul className="-mx-2 flex flex-col">
          {shown.map((report) => (
            <li key={report.id}>
              <SignalRow report={report} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SignalRow({ report }: { report: SignalReport }) {
  const title = humanizeReportTitle(report.title, "Untitled report");
  const headline = deriveHeadline(report.summary);
  const hasSource = hasKnownSourceProduct(report.source_products);
  return (
    <button
      type="button"
      onClick={() => navigateToReport(report.id)}
      className="flex w-full items-start gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-fill-hover"
    >
      <PriorityMonogram priority={report.priority} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate font-medium text-foreground text-xs">
          {title}
        </span>
        {headline ? (
          <span className="line-clamp-2 text-muted-foreground text-xxs">
            {headline}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 items-center gap-2 text-muted-foreground text-xxs">
        {hasSource ? (
          <InboxMetaSourceStack sourceProducts={report.source_products} />
        ) : null}
        <RelativeTimestamp timestamp={report.updated_at ?? report.created_at} />
      </span>
    </button>
  );
}
