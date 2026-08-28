import { FileTextIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import {
  AskAboutSelection,
  quoteSelection,
} from "@posthog/ui/features/inbox/components/AskAboutSelection";
import { ReportFeedbackFooter } from "@posthog/ui/features/inbox/components/detail/ReportFeedbackFooter";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { ReportChatSidebar } from "@posthog/ui/features/inbox/components/ReportChatSidebar";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportVerdictBanner } from "@posthog/ui/features/inbox/components/ReportVerdictBanner";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { useCallback, useEffect, useRef } from "react";

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
  backTo = "/inbox/reports",
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
 * A report reads story-first: the summary and charts, then the evidence.
 * The document stays pure content while its conversation owns follow-up
 * actions. Pipeline machinery (runs, activity logs, reviewer reasoning)
 * deliberately doesn't render.
 *
 * The report owns its own scroll so the chat dock can sit full-height beside
 * it: reading and asking share one screen, and highlighting a passage quotes
 * it into the chat.
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
  const chatOpen = useReportChatPanelStore((s) => s.open);
  const setChatOpen = useReportChatPanelStore((s) => s.setOpen);
  const setPendingQuote = useReportChatPanelStore((s) => s.setPendingQuote);
  const contentRef = useRef<HTMLDivElement>(null);

  // Each report opens as a document. Conversation remains explicit through the action box.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset when the route changes to another report.
  useEffect(() => {
    setChatOpen(false);
  }, [report.id, setChatOpen]);

  const handleAsk = useCallback(
    (text: string) => {
      setPendingQuote(report.id, quoteSelection(text));
      setChatOpen(true);
    },
    [report.id, setPendingQuote, setChatOpen],
  );

  return (
    <div className="flex h-full min-h-0">
      <div ref={contentRef} className="min-w-0 flex-1 overflow-y-auto">
        <InboxDetailFrame
          report={report}
          backTo={backTo}
          backLabel={backLabel}
          fallbackTitle="Untitled report"
          primaryAction={
            <ReportDetailActions report={report} placement="header" />
          }
          aboveSummary={
            <ReportVerdictBanner
              key={report.id}
              report={report}
              initialEngagementOnly
            />
          }
          summarySection={{ Icon: FileTextIcon, title: "Summary" }}
          footer={<ReportFeedbackFooter report={report} />}
          evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
        />
      </div>
      <AskAboutSelection containerRef={contentRef} onAsk={handleAsk} />
      {chatOpen && <ReportChatSidebar report={report} />}
    </div>
  );
}
