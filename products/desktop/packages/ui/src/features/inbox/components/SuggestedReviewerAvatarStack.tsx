import {
  suggestedReviewerDisplayName,
  toSuggestedReviewerWriteContent,
} from "@posthog/core/inbox/artefacts";
import { selectSuggestedReviewersArtefact } from "@posthog/core/inbox/reportArtefacts";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import type { InboxReportActionSurface } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportArtefactsResponse,
} from "@posthog/shared/types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { SuggestedReviewerAvatar } from "@posthog/ui/features/inbox/components/utils/SuggestedReviewerAvatar";
import {
  useInboxReportArtefacts,
  useUpdateSuggestedReviewers,
} from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";

const MAX_VISIBLE = 4;
// Keep this stable because autocapture insights and UI tests can depend on it.
const REMOVE_SELF_DATA_ATTR = "inbox-remove-self-from-reviewers";
const REMOVE_SELF_LABEL = "Remove me from reviewers";

interface SuggestedReviewerAvatarStackProps {
  report: SignalReport;
  artefacts?: SignalReportArtefactsResponse | null;
  /** Analytics surface for the remove-self action; the stack lives on list
   * cards by default, but the detail header reuses it. */
  surface?: InboxReportActionSurface;
}

export function SuggestedReviewerAvatarStack({
  report,
  artefacts,
  surface = "list_row",
}: SuggestedReviewerAvatarStackProps) {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client, enabled: !!client });
  const { data } = useInboxReportArtefacts(report.id, {
    enabled: artefacts === undefined,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
  const { mutate: updateReviewers, isPending } = useUpdateSuggestedReviewers(
    report.id,
  );
  const fireAction = useReportActionTracker(report, surface);
  const reviewerArtefact = selectSuggestedReviewersArtefact(
    artefacts?.results ?? data?.results ?? [],
  );
  const reviewers = (reviewerArtefact?.content ?? []).filter(
    (reviewer) => reviewer.github_login,
  );
  if (reviewers.length === 0) {
    return null;
  }

  const currentReviewer = reviewers.find(
    (reviewer) => reviewer.user?.uuid === currentUser?.uuid,
  );
  const visible = reviewers.slice(0, MAX_VISIBLE);
  const overflow = reviewers.length - visible.length;
  const reviewerCountLabel = `${reviewers.length} suggested reviewer${reviewers.length === 1 ? "" : "s"}`;
  const avatarStack = (
    <span className="-space-x-1.5 flex items-center">
      <span className="sr-only">{reviewerCountLabel}</span>
      {visible.map((reviewer) => (
        <SuggestedReviewerAvatar
          key={reviewer.github_login}
          githubLogin={reviewer.github_login}
          size="sm"
          className="ring-(--color-panel-solid) ring-2"
        />
      ))}
      {overflow > 0 ? (
        <span className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-(--gray-3) px-1 font-semibold text-[9px] text-gray-11 leading-none ring-(--color-panel-solid) ring-2">
          +{overflow}
        </span>
      ) : null}
    </span>
  );

  const removeSelf = () => {
    if (!currentReviewer || !reviewerArtefact) return;
    const nextReviewers = reviewerArtefact.content.filter(
      (reviewer) => reviewer.user?.uuid !== currentUser?.uuid,
    );
    fireAction("remove_suggested_reviewer", {
      suggested_reviewer_login: currentReviewer.github_login,
      suggested_reviewer_uuid: currentReviewer.user?.uuid,
    });
    updateReviewers({
      artefactId: reviewerArtefact.id,
      content: toSuggestedReviewerWriteContent(nextReviewers),
      optimisticReviewers: nextReviewers,
    });
  };

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="link-muted"
            size="xs"
            className="h-auto p-0 no-underline hover:no-underline"
            aria-label="View suggested reviewer rationale"
            onClick={(event) => event.stopPropagation()}
          />
        }
      >
        {avatarStack}
      </PopoverTrigger>
      <PopoverContent
        align="end"
        side="bottom"
        sideOffset={8}
        className="flex w-96 flex-col gap-0 overflow-hidden p-0"
      >
        <div className="border-(--gray-6) border-b px-3 py-2 font-medium text-[13px]">
          Suggested reviewers
        </div>
        <div className="max-h-80 overflow-y-auto overscroll-contain p-2">
          <Accordion
            multiple
            defaultValue={
              reviewers[0]?.github_login ? [reviewers[0].github_login] : []
            }
          >
            {reviewers.map((reviewer) => (
              <AccordionItem
                key={reviewer.github_login}
                value={reviewer.github_login}
              >
                <AccordionTrigger>
                  {suggestedReviewerDisplayName(reviewer)}
                </AccordionTrigger>
                <AccordionContent>
                  <div className="flex flex-col gap-2 pb-2 text-[12px] text-gray-11 leading-relaxed">
                    {reviewer.relevant_commits.length > 0 ? (
                      reviewer.relevant_commits.map((commit) => (
                        <p key={commit.sha}>{commit.reason}</p>
                      ))
                    ) : (
                      <p>Suggested by the agent</p>
                    )}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
        {currentReviewer && reviewerArtefact ? (
          <div className="border-(--gray-6) border-t p-2">
            <Button
              type="button"
              variant="outline"
              size="xs"
              className="w-full"
              data-attr={REMOVE_SELF_DATA_ATTR}
              loading={isPending}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                removeSelf();
              }}
            >
              {REMOVE_SELF_LABEL}
            </Button>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
