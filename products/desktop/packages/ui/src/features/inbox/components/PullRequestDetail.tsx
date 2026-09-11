import { GitPullRequestIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  primaryReportPullRequest,
  reportPullRequests,
} from "@posthog/core/inbox/reportPullRequests";
import type { SignalReport } from "@posthog/shared/types";
import { ReportFeedbackFooter } from "@posthog/ui/features/inbox/components/detail/ReportFeedbackFooter";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxMetaSeparator } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { ReportChatLayout } from "@posthog/ui/features/inbox/components/ReportDetail";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportReviewersSection } from "@posthog/ui/features/inbox/components/ReportReviewersSection";
import { ReportImplementationPrLink } from "@posthog/ui/features/inbox/components/utils/ReportImplementationPrLink";
import { ReportTrackerIssueLink } from "@posthog/ui/features/inbox/components/utils/ReportTrackerIssueLink";
import { PrCommentsSection } from "@posthog/ui/features/pr-review/PrCommentsSection";
import { PrDecisionBlock } from "@posthog/ui/features/pr-review/PrDecisionBlock";
import { PrFilesChangedSection } from "@posthog/ui/features/pr-review/PrFilesChangedSection";
import { useState } from "react";
import { ReportPullRequestSelector } from "./ReportPullRequestSelector";

interface PullRequestDetailProps {
  reportId: string;
  cachedReport?: SignalReport | null;
}

export function PullRequestDetail({
  reportId,
  cachedReport = null,
}: PullRequestDetailProps) {
  return (
    <InboxReportDetailGate
      reportId={reportId}
      cachedReport={cachedReport}
      backTo="/inbox/pulls"
      backLabel="Back to pull requests"
      missingCopy="This pull request couldn't be found. It may have been deleted."
    >
      {(report) => <PullRequestDetailContent report={report} />}
    </InboxReportDetailGate>
  );
}

/**
 * A report whose PR exists reads as: the story (summary + charts), then the
 * decision (approve / merge, big), then the discussion. The per-check CI
 * matrix, the runs log, and the activity log deliberately don't render —
 * they're pipeline machinery, and the decision block distills what matters
 * from them into one line.
 */
export function PullRequestDetailContent({ report }: { report: SignalReport }) {
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const prs = reportPullRequests(report);
  const selectedPr =
    prs.find((pr) => pr.url === selectedUrl) ??
    primaryReportPullRequest(report);
  const prUrl = parsePrUrl(selectedPr.url) ? selectedPr.url : null;

  return (
    <ReportChatLayout report={report}>
      <InboxDetailFrame
        report={report}
        fallbackTitle="Untitled pull request"
        metaSuffix={
          prUrl ? (
            <>
              <InboxMetaSeparator />
              {prs.length > 1 ? (
                <ReportPullRequestSelector
                  pullRequests={prs}
                  value={prUrl}
                  onValueChange={setSelectedUrl}
                />
              ) : (
                <ReportImplementationPrLink prUrl={prUrl} size="md" />
              )}
              <ReportTrackerIssueLink report={report} />
            </>
          ) : (
            <ReportTrackerIssueLink report={report} />
          )
        }
        primaryAction={
          <ReportDetailActions
            report={report}
            prUrl={prUrl}
            placement="header"
          />
        }
        showDismiss={false}
        summarySection={{ Icon: GitPullRequestIcon, title: "Summary" }}
        secondaryTab={
          prUrl
            ? {
                label: (
                  <>
                    Changed code
                    <PrDiffStats prUrl={prUrl} hideWhileLoading />
                  </>
                ),
                content: (
                  <PrFilesChangedSection key={prUrl} prUrl={prUrl} bare />
                ),
              }
            : undefined
        }
        belowSummary={
          prUrl && (
            <>
              <PrDecisionBlock key={`decision:${prUrl}`} prUrl={prUrl} />
              <PrCommentsSection key={`comments:${prUrl}`} prUrl={prUrl} />
            </>
          )
        }
        footer={<ReportFeedbackFooter report={report} />}
        evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
      >
        <ReportReviewersSection report={report} />
      </InboxDetailFrame>
    </ReportChatLayout>
  );
}
