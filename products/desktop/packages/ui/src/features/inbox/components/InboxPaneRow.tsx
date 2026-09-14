import type { SignalReport } from "@posthog/shared/types";
import { InboxReportContextMenu } from "@posthog/ui/features/inbox/components/InboxReportContextMenu";
import { InboxReportReadButton } from "@posthog/ui/features/inbox/components/InboxReportReadButton";
import { SelfDrivingReportListItem } from "@posthog/ui/features/inbox/components/SelfDrivingReportListItem";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportReadState } from "@posthog/ui/features/inbox/hooks/useInboxReportReadState";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import type { ReactElement } from "react";

/** One report in the rail's Self-driving list. */
export function InboxPaneRow({
  report,
  isSelected,
  optionValue,
}: {
  report: SignalReport;
  isSelected: boolean;
  optionValue: string;
}): ReactElement {
  const { isUnread } = useInboxReportReadState(report.id);
  const { pointerHandlers } = useInboxReportDetailPrefetch({
    to: "/reports/$reportId",
    params: { reportId: report.id },
  });
  return (
    <InboxReportContextMenu report={report}>
      <SelfDrivingReportListItem
        report={report}
        isSelected={isSelected}
        compact
        asOption
        optionValue={optionValue}
        emphasized={isUnread}
        actions={<InboxReportReadButton reportId={report.id} />}
        actionCount={1}
        actionsVisibility="always"
        onClick={() => navigateToInboxReportDetail(report.id)}
        {...pointerHandlers}
      />
    </InboxReportContextMenu>
  );
}
