import {
  CopyIcon,
  FileTextIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ReportActivitySection } from "@posthog/ui/features/inbox/components/detail/ReportActivitySection";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportTasksSection } from "@posthog/ui/features/inbox/components/ReportTasksSection";
import { SuggestedReviewersSection } from "@posthog/ui/features/inbox/components/SuggestedReviewersSection";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";

interface ReportDetailProps {
  reportId: string;
  cachedReport?: SignalReport | null;
}

export function ReportDetail({
  reportId,
  cachedReport = null,
}: ReportDetailProps) {
  return (
    <InboxReportDetailGate
      reportId={reportId}
      cachedReport={cachedReport}
      backTo="/code/inbox/reports"
      backLabel="Back to reports"
      missingCopy="This report couldn't be found. It may have been deleted."
    >
      {(report) => <ReportDetailContent report={report} />}
    </InboxReportDetailGate>
  );
}

function ReportDetailContent({ report }: { report: SignalReport }) {
  return (
    <InboxDetailFrame
      report={report}
      backTo="/code/inbox/reports"
      backLabel="Back to reports"
      fallbackTitle="Untitled report"
      primaryAction={
        <>
          <ReportDetailActions report={report} />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => copyInboxReportLink(report)}
            title="Copy a deep link to this report"
          >
            <CopyIcon size={12} />
          </Button>
        </>
      }
      summarySection={{ Icon: FileTextIcon, title: "Summary" }}
      evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
    >
      <ReportTasksSection report={report} />
      <SuggestedReviewersSection report={report} />
      <ReportActivitySection reportId={report.id} />
    </InboxDetailFrame>
  );
}
