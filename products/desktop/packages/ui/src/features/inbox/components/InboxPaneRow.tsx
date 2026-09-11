import { Button, cn } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { InboxReportContextMenu } from "@posthog/ui/features/inbox/components/InboxReportContextMenu";
import { SelfDrivingReportListItem } from "@posthog/ui/features/inbox/components/SelfDrivingReportListItem";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useInboxReportReadState } from "@posthog/ui/features/inbox/hooks/useInboxReportReadState";
import { RAIL_HOVER_ACTIONS_CLASS } from "@posthog/ui/features/sidebar/components/RailListItem";
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
  const { isUnread, enabled, setRead } = useInboxReportReadState(report.id);
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
        actions={
          enabled ? (
            <Button
              variant="default"
              size="icon-sm"
              className={cn(!isUnread && RAIL_HOVER_ACTIONS_CLASS)}
              aria-label={
                isUnread ? "Mark report as read" : "Mark report as unread"
              }
              title={isUnread ? "Unread. Mark as read" : "Mark as unread"}
              onClick={() => setRead(isUnread)}
            >
              <span
                className={cn(
                  "size-2 rounded-full",
                  isUnread ? "bg-(--blue-9)" : "border border-(--gray-9)",
                )}
              />
            </Button>
          ) : undefined
        }
        actionCount={1}
        actionsVisibility="always"
        onClick={() => navigateToInboxReportDetail(report.id)}
        {...pointerHandlers}
      />
    </InboxReportContextMenu>
  );
}
