import { InfoIcon, PlusIcon, UsersThreeIcon } from "@phosphor-icons/react";
import { toSuggestedReviewerWriteContent } from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport, SuggestedReviewer } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReviewerSearchList } from "@posthog/ui/features/inbox/components/ReviewerSearchList";
import { SuggestedReviewersList } from "@posthog/ui/features/inbox/components/SuggestedReviewersList";
import {
  useInboxReportArtefacts,
  useUpdateSuggestedReviewers,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  useReportActionResultTracker,
  useReportActionTracker,
} from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useMemo, useState } from "react";

export function ReportReviewersSection({ report }: { report: SignalReport }) {
  const fireAction = useReportActionTracker(report);
  const trackResult = useReportActionResultTracker(report);
  const { data } = useInboxReportArtefacts(report.id);
  const artefact = selectSuggestedReviewersArtefact(data?.results ?? []);
  const reviewers = useMemo(() => artefact?.content ?? [], [artefact]);
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
    <ReportReviewersSectionView
      report={report}
      reviewers={reviewers}
      disabled={isPending}
      onRemove={removeReviewer}
    />
  );
}

export function ReportReviewersSectionView({
  report,
  reviewers,
  disabled,
  onRemove,
}: {
  report: SignalReport;
  reviewers: SuggestedReviewer[];
  disabled: boolean;
  onRemove: (reviewer: SuggestedReviewer) => void;
}) {
  const [addOpen, setAddOpen] = useState(false);

  return (
    <DetailSection
      Icon={UsersThreeIcon}
      title="Suggested reviewers"
      collapsible
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  type="button"
                  aria-label="About suggested reviewers"
                  className="rounded-sm p-0.5 text-muted-foreground hover:bg-fill-hover hover:text-foreground"
                />
              }
            >
              <InfoIcon size={12} />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-80">
              PostHog uses these suggestions to route the report. Add reviewers
              on the pull request to request a GitHub review.
            </TooltipContent>
          </Tooltip>
          <span className="text-[12px] text-gray-10 tabular-nums">
            {reviewers.length}
          </span>
        </div>
        <Popover open={addOpen} onOpenChange={setAddOpen}>
          <PopoverTrigger
            render={
              <Button
                type="button"
                variant="link-muted"
                size="xs"
                disabled={disabled}
                data-attr="inbox-report-add-reviewer"
              >
                {disabled ? <Spinner /> : <PlusIcon size={12} />}
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
      {reviewers.length === 0 ? (
        <p className="m-0 text-muted-foreground text-xs">
          No suggested reviewers. Select Add to suggest one.
        </p>
      ) : (
        <SuggestedReviewersList
          reviewers={reviewers}
          disabled={disabled}
          onRemove={onRemove}
        />
      )}
    </DetailSection>
  );
}
