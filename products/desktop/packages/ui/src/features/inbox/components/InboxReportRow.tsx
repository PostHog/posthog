import type { SignalReport } from "@posthog/shared/types";
import { InboxReportContextMenu } from "@posthog/ui/features/inbox/components/InboxReportContextMenu";
import { InboxReportRowView } from "@posthog/ui/features/inbox/components/InboxReportRowView";
import { ReportRestoreButton } from "@posthog/ui/features/inbox/components/ReportRestoreButton";
import { SuggestedReviewerAvatarStack } from "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack";
import { useInboxReportDetailPrefetch } from "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch";
import { useReportImplementationStates } from "@posthog/ui/features/inbox/hooks/useReportImplementationStates";
import { navigateToInboxReportDetail } from "@posthog/ui/router/navigationBridge";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

export function InboxReportRow({
  report,
}: {
  report: SignalReport;
}): React.JSX.Element {
  const { pointerHandlers } = useInboxReportDetailPrefetch({
    to: "/reports/$reportId",
    params: { reportId: report.id },
  });

  const { states } = useReportImplementationStates([report]);

  return (
    <InboxReportContextMenu report={report}>
      <InboxReportRowView
        report={report}
        implementationState={states.get(report.id)}
        prefetchHandlers={pointerHandlers}
        reviewers={<SuggestedReviewerAvatarStack report={report} />}
        restoreAction={<ReportRestoreButton report={report} />}
        onOpen={() => navigateToInboxReportDetail(report.id)}
        onOpenPr={openExternalUrl}
      />
    </InboxReportContextMenu>
  );
}
