import { WarningIcon } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { Tooltip } from "@radix-ui/themes";

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
    return (
      <Tooltip content="Tracker issue for this pull request">
        <a
          href={report.tracker_issue_url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className={cn(badgeClass, "bg-gray-4 text-gray-11 hover:bg-gray-5")}
        >
          {report.tracker_issue_reference ?? "Tracked"}
        </a>
      </Tooltip>
    );
  }

  if (report.tracker_issue_error) {
    return (
      <Tooltip content={report.tracker_issue_error}>
        <span className={cn(badgeClass, "bg-amber-4 text-amber-11")}>
          <WarningIcon size={12} weight="bold" />
          No tracker issue
        </span>
      </Tooltip>
    );
  }

  return null;
}
