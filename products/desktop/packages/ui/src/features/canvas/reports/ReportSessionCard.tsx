import { ArrowRightIcon, FileTextIcon } from "@phosphor-icons/react";
import { deriveHeadline } from "@posthog/core/inbox/reportPresentation";
import { Badge, Card, CardContent, cn } from "@posthog/quill";
import { formatRelativeTimeLong } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { SignalReportPriorityBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge";
import { SignalReportStatusBadge } from "@posthog/ui/features/inbox/components/utils/SignalReportStatusBadge";
import { Link } from "@tanstack/react-router";

export function ReportSessionCard({
  channelId,
  report,
  archived = false,
}: {
  channelId: string;
  report: SignalReport;
  archived?: boolean;
}) {
  const headline = deriveHeadline(report.summary);
  return (
    <Card
      className={cn(
        "transition-colors hover:bg-fill-hover",
        archived && "opacity-75",
      )}
    >
      <Link
        to="/website/$channelId/reports/$reportId"
        params={{ channelId, reportId: report.id }}
        className="block text-inherit no-underline focus-visible:outline-none"
      >
        <CardContent className="flex items-start gap-3 p-4">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-fill-secondary">
            <FileTextIcon size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex flex-wrap items-center gap-1.5">
              <span className="font-semibold text-sm">
                {report.title || "Untitled report"}
              </span>
              {report.priority && (
                <SignalReportPriorityBadge priority={report.priority} />
              )}
              <SignalReportStatusBadge status={report.status} />
              {report.is_suggested_reviewer && (
                <Badge variant="info">For you</Badge>
              )}
            </div>
            {headline && (
              <p className="line-clamp-2 text-muted text-sm">{headline}</p>
            )}
            <p className="mt-2 text-muted text-xs">
              Updated{" "}
              {formatRelativeTimeLong(report.updated_at ?? report.created_at)}
            </p>
          </div>
          <ArrowRightIcon className="mt-1 shrink-0 text-muted" size={14} />
        </CardContent>
      </Link>
    </Card>
  );
}
