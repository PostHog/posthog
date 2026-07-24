import { ReadCvLogoIcon } from "@phosphor-icons/react";
import { isReportTabReport } from "@posthog/core/inbox/reportMembership";
import { InboxReportListTab } from "@posthog/ui/features/inbox/components/InboxReportListTab";
import { ReportCard } from "@posthog/ui/features/inbox/components/ReportCard";

export function ReportsTab() {
  return (
    <InboxReportListTab
      predicate={isReportTabReport}
      Card={ReportCard}
      searchPlaceholder="Search reports…"
      emptyState={{
        Icon: ReadCvLogoIcon,
        forYouTitle: "No reports for you yet",
        entireProjectTitle: "No reports in the project yet",
        teammateTitle: "No reports for this reviewer yet",
        description:
          "Reports are what Responders surface when there's something worth your judgment but no clean code change to draft.",
      }}
    />
  );
}
