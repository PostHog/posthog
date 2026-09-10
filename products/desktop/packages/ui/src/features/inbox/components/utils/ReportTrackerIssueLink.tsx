import { WarningIcon } from "@phosphor-icons/react";
import {
  cn,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";

/**
 * The tracker issue behind a report's pull request, or why there is none.
 *
 * A team that cannot merge without a tracked work item has to spot the pull requests that lack one,
 * so the failure sits next to the pull request badge rather than in a surface of its own.
 */
export function ReportTrackerIssueLink({ report }: { report: SignalReport }) {
  const badgeClass =
    "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium";

  if (report.tracker_issue_url) {
    const trigger = (
      <a
        href={report.tracker_issue_url}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => e.stopPropagation()}
        className={cn(badgeClass, "bg-gray-4 text-gray-11 hover:bg-gray-5")}
      >
        {report.tracker_issue_reference ?? "Tracked"}
      </a>
    );
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger render={trigger} />
          <TooltipContent>Tracker issue for this report</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  if (report.tracker_issue_error) {
    const trigger = (
      <button
        type="button"
        aria-label={`No tracker issue: ${report.tracker_issue_error}`}
        className={cn(badgeClass, "bg-amber-4 text-amber-11")}
      >
        <WarningIcon size={12} weight="bold" />
        No tracker issue
      </button>
    );
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger render={trigger} />
          <TooltipContent>{report.tracker_issue_error}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return null;
}
