import { FileTextIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import {
  deriveHeadline,
  humanizeReportTitle,
} from "@posthog/core/inbox/reportPresentation";
import { Button, Card, CardContent } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { ReportRestoreButton } from "@posthog/ui/features/inbox/components/ReportRestoreButton";
import {
  ReportStateMonogram,
  reportRunState,
} from "@posthog/ui/features/inbox/components/ReportStateMonogram";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useMemo } from "react";

/**
 * A report's compact card in the space feed — lighter than a session card:
 * priority, title, one-line summary, and where they apply a for-you badge and
 * PR marker. Clicking anywhere opens the report detail; hover actions carry
 * the inbox's triage gestures (Review, Archive / Restore).
 */
export function ReportFeedRow({
  report,
  onOpenReport,
}: {
  report: SignalReport;
  onOpenReport: (reportId: string) => void;
}) {
  const title = humanizeReportTitle(report.title, "Untitled report");
  const headline = useMemo(
    () => deriveHeadline(report.summary),
    [report.summary],
  );
  const runState = reportRunState(report);
  const archived = isDismissedReport(report);
  const { actionButton: archiveButton, dialog: archiveDialog } =
    useInboxReportDismissAction(report);

  return (
    <>
      <Card
        size="sm"
        className="group/report mx-auto my-1.5 w-full max-w-[660px] cursor-pointer rounded-xl py-0 transition-colors hover:bg-(--gray-2)"
        onClick={() => onOpenReport(report.id)}
      >
        <CardContent className="flex flex-col gap-1 px-4 pt-3 pb-2.5">
          <div className="flex items-start gap-3">
            <ReportStateMonogram report={report} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="min-w-0 truncate font-semibold text-sm leading-snug">
                  {title}
                </span>
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
            {/* Triage without opening detail. Revealed on hover; stops
                propagation so the card click doesn't also fire. */}
            {/* biome-ignore lint/a11y/noStaticElementInteractions: propagation guard for the buttons inside, not an interactive element itself */}
            <span
              className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover/report:opacity-100"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => event.stopPropagation()}
            >
              {report.implementation_pr_url && !archived && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onOpenReport(report.id)}
                  title="Review this report's pull request"
                >
                  Review
                </Button>
              )}
              {archived ? (
                <ReportRestoreButton report={report} />
              ) : (
                archiveButton
              )}
            </span>
          </div>
          <div className="flex items-center gap-2 text-(--gray-9) text-xs">
            <InboxBadge className="gap-1">
              <FileTextIcon size={11} className="shrink-0" />
              Report
            </InboxBadge>
            {runState && (
              <InboxBadge variant={runState.badgeTone}>
                {runState.label}
              </InboxBadge>
            )}
            {archived && <InboxBadge>Archived</InboxBadge>}
            {report.priority && (
              <span className="text-(--gray-9)">· {report.priority}</span>
            )}
            <span>· {formatRelativeTimeShort(report.created_at)}</span>
          </div>
        </CardContent>
      </Card>
      {archiveDialog}
    </>
  );
}
