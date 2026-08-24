import {
  ArrowSquareOutIcon,
  CopyIcon,
  GitPullRequestIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { ReportActivitySection } from "@posthog/ui/features/inbox/components/detail/ReportActivitySection";
import { ReportFeedbackFooter } from "@posthog/ui/features/inbox/components/detail/ReportFeedbackFooter";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxMetaSeparator } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportRefundAction } from "@posthog/ui/features/inbox/components/ReportRefundAction";
import { ReportTasksSection } from "@posthog/ui/features/inbox/components/ReportTasksSection";
import { SuggestedReviewersSection } from "@posthog/ui/features/inbox/components/SuggestedReviewersSection";
import { ReportImplementationPrLink } from "@posthog/ui/features/inbox/components/utils/ReportImplementationPrLink";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { PrChecksSection } from "@posthog/ui/features/pr-review/PrChecksSection";
import { PrCommentsSection } from "@posthog/ui/features/pr-review/PrCommentsSection";
import { PrFilesChangedSection } from "@posthog/ui/features/pr-review/PrFilesChangedSection";
import { PrReviewActions } from "@posthog/ui/features/pr-review/PrReviewActions";

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

function PullRequestDetailContent({ report }: { report: SignalReport }) {
  const prRef = report.implementation_pr_url
    ? parsePrUrl(report.implementation_pr_url)
    : null;

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
            <span className="font-mono text-[12px] text-gray-11">
              {prRef.repoSlug}#{prRef.number}
            </span>
          </>
        ) : undefined
      }
      metaSuffix={
        report.implementation_pr_url ? (
          <>
            <InboxMetaSeparator />
            <ReportImplementationPrLink
              prUrl={report.implementation_pr_url}
              size="md"
            />
            <PrDiffStats
              prUrl={report.implementation_pr_url}
              hideWhileLoading
            />
          </>
        ) : undefined
      }
      primaryAction={
        <>
          {prRef && report.implementation_pr_url ? (
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => {
                // `prRef` non-null already proves the URL is canonical GitHub.
                window.open(
                  report.implementation_pr_url ?? "",
                  "_blank",
                  "noopener",
                );
              }}
              className="gap-2"
            >
              Open in GitHub
              <ArrowSquareOutIcon size={12} />
            </Button>
          ) : null}
          <ReportDetailActions report={report} />
          <ReportRefundAction report={report} />
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
      summarySection={{ Icon: GitPullRequestIcon, title: "Summary" }}
      secondaryTab={
        prRef && report.implementation_pr_url
          ? {
              label: (
                <>
                  Files changed
                  <PrDiffStats
                    prUrl={report.implementation_pr_url}
                    hideWhileLoading
                  />
                </>
              ),
              content: (
                <PrFilesChangedSection
                  prUrl={report.implementation_pr_url}
                  bare
                />
              ),
            }
          : undefined
      }
      belowSummary={
        <>
          {prRef && report.implementation_pr_url && (
            <>
              <PrCommentsSection prUrl={report.implementation_pr_url} />
              <PrReviewActions prUrl={report.implementation_pr_url} />
            </>
          )}
          <ReportFeedbackFooter report={report} />
        </>
      }
      evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
      aboveEvidence={
        <>
          {prRef && report.implementation_pr_url && (
            <PrChecksSection prUrl={report.implementation_pr_url} />
          )}
          <SuggestedReviewersSection report={report} />
        </>
      }
    >
      <ReportTasksSection report={report} />
      <ReportActivitySection
        reportId={report.id}
        // The Files changed tab already lists every changed file, so the
        // per-commit diff toggle in the activity log is redundant here.
        hideCommitDiffs={Boolean(prRef && report.implementation_pr_url)}
      />
    </InboxDetailFrame>
  );
}
