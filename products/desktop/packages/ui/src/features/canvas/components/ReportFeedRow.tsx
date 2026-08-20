import { FileTextIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import { deriveHeadline } from "@posthog/core/inbox/reportPresentation";
import { Card, CardContent } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { useMemo } from "react";

/**
 * A report's compact card in the space feed — lighter than a session card:
 * priority, title, one-line summary, and where they apply a for-you badge and
 * PR marker. Clicking anywhere opens the report detail.
 */
export function ReportFeedRow({
  report,
  onOpenReport,
}: {
  report: SignalReport;
  onOpenReport: (reportId: string) => void;
}) {
  const title = report.title?.trim() || "Untitled report";
  const headline = useMemo(
    () => deriveHeadline(report.summary),
    [report.summary],
  );

  return (
    <Card
      size="sm"
      className="mx-auto my-1.5 w-full max-w-[660px] cursor-pointer rounded-xl py-0 transition-colors hover:bg-(--gray-2)"
      onClick={() => onOpenReport(report.id)}
    >
      <CardContent className="flex flex-col gap-1 px-4 pt-3 pb-2.5">
        <div className="flex items-start gap-3">
          <PriorityMonogram priority={report.priority} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="min-w-0 truncate font-semibold text-sm leading-snug">
                {title}
              </span>
              {report.is_suggested_reviewer && <ForYouBadge />}
              {report.implementation_pr_url && (
                <GitPullRequestIcon
                  size={13}
                  className="shrink-0 text-(--gray-9)"
                  aria-label="Has a pull request"
                />
              )}
            </div>
            {headline && (
              <div className="mt-0.5 truncate text-(--gray-11) text-xs leading-normal">
                {headline}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 text-(--gray-9) text-xs">
          <InboxBadge className="gap-1">
            <FileTextIcon size={11} className="shrink-0" />
            Report
          </InboxBadge>
          <span>· {formatRelativeTimeShort(report.created_at)}</span>
        </div>
      </CardContent>
    </Card>
  );
}
