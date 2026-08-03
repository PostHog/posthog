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
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxMetaSeparator } from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import { PrDiffStats } from "@posthog/ui/features/inbox/components/PrDiffStats";
import { ReportDetailActions } from "@posthog/ui/features/inbox/components/ReportDetailActions";
import { ReportTasksSection } from "@posthog/ui/features/inbox/components/ReportTasksSection";
import { SuggestedReviewersSection } from "@posthog/ui/features/inbox/components/SuggestedReviewersSection";
import { ReportImplementationPrLink } from "@posthog/ui/features/inbox/components/utils/ReportImplementationPrLink";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { PrChecksSection } from "@posthog/ui/features/pr-review/PrChecksSection";
import { PrCommentsSection } from "@posthog/ui/features/pr-review/PrCommentsSection";
import { PrFilesChangedSection } from "@posthog/ui/features/pr-review/PrFilesChangedSection";
import { PrReviewActions } from "@posthog/ui/features/pr-review/PrReviewActions";
import { Text } from "@radix-ui/themes";

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
      backTo="/code/inbox/pulls"
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
      backTo="/code/inbox/pulls"
      backLabel="Back to pull requests"
      fallbackTitle="Untitled pull request"
      breadcrumb={
        prRef ? (
          <>
            <span className="text-(--gray-8)">/</span>
            <Text className="font-mono text-[12px] text-gray-11">
              {prRef.repoSlug}#{prRef.number}
            </Text>
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
        </>
      }
      summarySection={{ Icon: GitPullRequestIcon, title: "Summary" }}
      belowSummary={
        prRef && report.implementation_pr_url ? (
          <>
            <PrFilesChangedSection prUrl={report.implementation_pr_url} />
            <PrCommentsSection prUrl={report.implementation_pr_url} />
            <PrChecksSection prUrl={report.implementation_pr_url} />
            <PrReviewActions prUrl={report.implementation_pr_url} />
          </>
        ) : undefined
      }
      evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
    >
      <ReportTasksSection report={report} />
      <SuggestedReviewersSection report={report} />
      <ReportActivitySection
        reportId={report.id}
        // The main column already lists every changed file, so the
        // per-commit diff toggle in the activity log is redundant here.
        hideCommitDiffs={Boolean(prRef && report.implementation_pr_url)}
      />
    </InboxDetailFrame>
  );
}
