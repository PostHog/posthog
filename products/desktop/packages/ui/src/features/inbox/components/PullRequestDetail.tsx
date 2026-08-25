import { GitPullRequestIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import type { SignalReport } from "@posthog/shared/types";
import { ReportFeedbackFooter } from "@posthog/ui/features/inbox/components/detail/ReportFeedbackFooter";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxMetaSeparator } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportImplementationPrLink } from "@posthog/ui/features/inbox/components/utils/ReportImplementationPrLink";
import { PrCommentsSection } from "@posthog/ui/features/pr-review/PrCommentsSection";
import { PrDecisionBlock } from "@posthog/ui/features/pr-review/PrDecisionBlock";
import { PrFilesChangedSection } from "@posthog/ui/features/pr-review/PrFilesChangedSection";

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
function PullRequestDetailContent({ report }: { report: SignalReport }) {
  const prRef = report.implementation_pr_url
    ? parsePrUrl(report.implementation_pr_url)
    : null;
  const prUrl = prRef ? report.implementation_pr_url : null;

  return (
    <InboxDetailFrame
      report={report}
      backTo="/inbox/pulls"
      backLabel="Back to pull requests"
      fallbackTitle="Untitled pull request"
      breadcrumb={
        prRef ? (
          <>
            <span className="text-(--gray-8)">/</span>
            <span className="font-mono text-[13px] text-gray-11">
              {prRef.repoSlug}#{prRef.number}
            </span>
          </>
        ) : undefined
      }
      metaSuffix={
        prUrl ? (
          <>
            <InboxMetaSeparator />
            <ReportImplementationPrLink prUrl={prUrl} size="md" />
          </>
        ) : undefined
      }
      primaryAction={<ReportDetailActions report={report} prUrl={prUrl} />}
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
              content: <PrFilesChangedSection prUrl={prUrl} bare />,
            }
          : undefined
      }
      belowSummary={
        prUrl && (
          <>
            <PrDecisionBlock prUrl={prUrl} />
            <PrCommentsSection prUrl={prUrl} />
          </>
        )
      }
      footer={<ReportFeedbackFooter report={report} />}
      evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
    />
  );
}
