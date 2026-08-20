import { GitPullRequestIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { ForYouBadge } from "@posthog/ui/features/inbox/components/utils/ForYouBadge";
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
  const title = report.title?.trim() || "Untitled report";

  return (
    <>
      <SidebarItem
        depth={0}
        icon={<PriorityMonogram priority={report.priority} />}
        label={<span className="truncate">{title}</span>}
        isActive={isActive}
        onClick={() => onOpen(report.id)}
        badge={report.is_suggested_reviewer ? <ForYouBadge /> : undefined}
        endContent={
          <span className="flex items-center gap-1">
            {report.implementation_pr_url && (
              <GitPullRequestIcon
                size={13}
                className="text-(--gray-9)"
                aria-label="Has a pull request"
              />
            )}
            {actionButton}
          </span>
        }
      />
      {dialog}
    </>
  );
}
