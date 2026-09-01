import { UsersThreeIcon } from "@phosphor-icons/react";
import { suggestedReviewerDisplayName } from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import type { SignalReport } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { SuggestedReviewerAvatar } from "@posthog/ui/features/inbox/components/utils/SuggestedReviewerAvatar";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";

export function ReportReviewersSection({ report }: { report: SignalReport }) {
  const { data } = useInboxReportArtefacts(report.id);
  const reviewers = selectSuggestedReviewersArtefact(
    data?.results ?? [],
  )?.content;

  if (!reviewers || reviewers.length === 0) return null;

  return (
    <DetailSection
      Icon={UsersThreeIcon}
      title="Reviewers"
      collapsible
      rightSlot={
        <span className="text-[12px] text-gray-10 tabular-nums">
          {reviewers.length}
        </span>
      }
    >
      <div className="flex flex-col gap-4">
        {reviewers.map((reviewer) => (
          <div
            key={reviewer.user?.uuid ?? reviewer.github_login}
            className="flex min-w-0 flex-col gap-1.5"
          >
            <div className="flex items-center gap-2">
              {reviewer.github_login && (
                <SuggestedReviewerAvatar
                  githubLogin={reviewer.github_login}
                  size="sm"
                />
              )}
              <span className="truncate font-medium text-[13px] text-gray-12">
                {suggestedReviewerDisplayName(reviewer)}
              </span>
            </div>
            {reviewer.relevant_commits.map((commit) => (
              <p
                key={commit.sha}
                className="m-0 text-[12px] text-gray-10 leading-relaxed"
              >
                {commit.reason}
              </p>
            ))}
          </div>
        ))}
      </div>
    </DetailSection>
  );
}
