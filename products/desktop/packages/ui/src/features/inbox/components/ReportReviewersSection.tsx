import { PlusIcon, UsersThreeIcon, XIcon } from "@phosphor-icons/react";
import {
  suggestedReviewerDisplayName,
  toSuggestedReviewerWriteContent,
} from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
} from "@posthog/quill";
import type { SignalReport, SuggestedReviewer } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReviewerSearchList } from "@posthog/ui/features/inbox/components/ReviewerSearchList";
import { SuggestedReviewerAvatar } from "@posthog/ui/features/inbox/components/utils/SuggestedReviewerAvatar";
import {
  useInboxReportArtefacts,
  useUpdateSuggestedReviewers,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  useReportActionResultTracker,
  useReportActionTracker,
} from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useMemo, useState } from "react";

export function ReportReviewersSection({ report }: { report: SignalReport }) {
  const fireAction = useReportActionTracker(report);
  const trackResult = useReportActionResultTracker(report);
  const { data } = useInboxReportArtefacts(report.id);
  const artefact = selectSuggestedReviewersArtefact(data?.results ?? []);
  const reviewers = useMemo(() => artefact?.content ?? [], [artefact]);
  const [addOpen, setAddOpen] = useState(false);
  const { mutate: updateReviewers, isPending } = useUpdateSuggestedReviewers(
    report.id,
  );

  if (!data) return null;

  const removeReviewer = (reviewer: SuggestedReviewer): void => {
    const next = reviewers.filter((candidate) => candidate !== reviewer);
    fireAction("remove_suggested_reviewer", {
      suggested_reviewer_login: reviewer.github_login || undefined,
      suggested_reviewer_uuid: reviewer.user?.uuid,
    });
    const startedAt = Date.now();
    updateReviewers(
      {
        content: toSuggestedReviewerWriteContent(next),
        optimisticReviewers: next,
      },
      {
        onSuccess: () =>
          trackResult("remove_suggested_reviewer", "succeeded", startedAt),
        onError: () =>
          trackResult(
            "remove_suggested_reviewer",
            "failed",
            startedAt,
            "request_failed",
          ),
      },
    );
  };

  return (
    <DetailSection
      Icon={UsersThreeIcon}
      title="Reviewers"
      collapsible
      rightSlot={
        <div className="flex items-center gap-2">
          <span className="text-[12px] text-gray-10 tabular-nums">
            {reviewers.length}
          </span>
          <Popover open={addOpen} onOpenChange={setAddOpen}>
            <PopoverTrigger
              render={
                <Button
                  type="button"
                  variant="link-muted"
                  size="xs"
                  disabled={isPending}
                  data-attr="inbox-report-add-reviewer"
                >
                  {isPending ? <Spinner /> : <PlusIcon size={12} />}
                  Add
                </Button>
              }
            />
            <PopoverContent
              align="end"
              side="bottom"
              sideOffset={6}
              className="min-w-[280px] max-w-[320px] p-0"
            >
              <ReviewerSearchList
                report={report}
                surface="detail_pane"
                enabled={addOpen}
              />
            </PopoverContent>
          </Popover>
        </div>
      }
    >
      {reviewers.length === 0 ? (
        <p className="m-0 text-[12px] text-gray-10">No reviewers assigned.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {reviewers.map((reviewer) => (
            <div
              key={reviewer.user?.uuid ?? reviewer.github_login}
              className="flex min-w-0 items-start justify-between gap-2"
            >
              <div className="flex min-w-0 flex-col gap-1.5">
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
              <Button
                type="button"
                variant="link-muted"
                size="icon-xs"
                aria-label={`Remove ${suggestedReviewerDisplayName(reviewer)}`}
                disabled={isPending}
                data-attr="inbox-report-remove-reviewer"
                onClick={() => removeReviewer(reviewer)}
              >
                <XIcon size={12} />
              </Button>
            </div>
          ))}
        </div>
      )}
    </DetailSection>
  );
}
