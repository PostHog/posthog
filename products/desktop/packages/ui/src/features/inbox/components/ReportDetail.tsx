import { FileTextIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { ReportFeedbackFooter } from "@posthog/ui/features/inbox/components/detail/ReportFeedbackFooter";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { ReportDecisionSection } from "@posthog/ui/features/inbox/components/ReportDecisionSection";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";

interface ReportDetailProps {
  reportId: string;
  cachedReport?: SignalReport | null;
  /** Where the back link points; the inbox Reports tab unless re-homed. */
  backTo?: string;
  backLabel?: string;
  /** Off when hosted on the in-space route, which has no per-status URLs. */
  statusRedirect?: boolean;
}

export function ReportDetail({
  reportId,
  cachedReport = null,
  backTo = "/code/inbox/reports",
  backLabel = "Back to reports",
  statusRedirect = true,
}: ReportDetailProps) {
  return (
    <InboxReportDetailGate
      reportId={reportId}
      cachedReport={cachedReport}
      backTo={backTo}
      backLabel={backLabel}
      statusRedirect={statusRedirect}
      missingCopy="This report couldn't be found. It may have been deleted."
    >
      {(report) => (
        <ReportDetailContent
          report={report}
          backTo={backTo}
          backLabel={backLabel}
        />
      )}
    </InboxReportDetailGate>
  );
}

/**
 * A report reads as: the story (summary + charts), then its one ask (the
 * decision block), then the evidence. Pipeline machinery (runs, activity
 * logs, reviewer reasoning) deliberately doesn't render.
 */
function ReportDetailContent({
  report,
  backTo,
  backLabel,
}: {
  report: SignalReport;
  backTo: string;
  backLabel: string;
}) {
  return (
    <InboxDetailFrame
      report={report}
      backTo={backTo}
      backLabel={backLabel}
      fallbackTitle="Untitled report"
      primaryAction={<ReportDetailActions report={report} />}
      summarySection={{ Icon: FileTextIcon, title: "Summary" }}
      belowSummary={
        <>
          <ReportDecisionSection report={report} />
          <ReportFeedbackFooter report={report} />
        </>
      }
      evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
    />
  );
}
