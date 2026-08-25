import { GitPullRequestIcon } from "@phosphor-icons/react";
import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import { humanizeReportTitle } from "@posthog/core/inbox/reportPresentation";
import type { SignalReport } from "@posthog/shared/types";
import { ReportRestoreButton } from "@posthog/ui/features/inbox/components/ReportRestoreButton";
import { ReportStateMonogram } from "@posthog/ui/features/inbox/components/ReportStateMonogram";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";

/** One report in a space's Reports tab. Clicking opens the report detail. */
export function ReportRow({
  report,
  isActive,
  onOpen,
}: {
  report: SignalReport;
  isActive: boolean;
  onOpen: (reportId: string) => void;
}) {
  const { actionButton, dialog } = useInboxReportDismissAction(report);
  const title = humanizeReportTitle(report.title, "Untitled report");

  return (
    <>
      <SidebarItem
        depth={0}
        icon={<ReportStateMonogram report={report} />}
        label={<span className="truncate">{title}</span>}
        isActive={isActive}
        onClick={() => onOpen(report.id)}
        endContent={
          <span className="flex items-center gap-1">
            {report.implementation_pr_url && (
              <GitPullRequestIcon
                size={13}
                className="text-(--gray-9)"
                aria-label="Has a pull request"
              />
            )}
            {/* SidebarItem is itself a button, so the archive/restore controls
                stop propagation to keep a triage click from also opening the
                report. */}
            {/* biome-ignore lint/a11y/noStaticElementInteractions: propagation guard for the buttons inside, not an interactive element itself */}
            <span
              className="flex items-center gap-1"
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => event.stopPropagation()}
            >
              {isDismissedReport(report) ? (
                <ReportRestoreButton report={report} />
              ) : (
                actionButton
              )}
            </span>
          </span>
        }
      />
      {dialog}
    </>
  );
}
