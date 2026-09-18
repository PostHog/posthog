import { XIcon } from "@phosphor-icons/react";
import {
  buildSuggestedReviewerItems,
  isScoutSuggestedReviewer,
  suggestedReviewerDisplayName,
  suggestedReviewerExplanation,
  suggestedReviewerSourceLabel,
} from "@posthog/core/inbox/artefacts";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SuggestedReviewer } from "@posthog/shared/types";
import { ReviewerAvatar } from "@posthog/ui/features/inbox/components/ReviewerAvatar";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { SuggestedReviewerAvatar } from "@posthog/ui/features/inbox/components/utils/SuggestedReviewerAvatar";
import { useState } from "react";

const MAX_VISIBLE_SUGGESTIONS = 5;
const UNLINKED_REVIEWER_MESSAGE =
  "This reviewer is not linked to a PostHog member and cannot receive the report.";

function ReviewerIdentity({ reviewer }: { reviewer: SuggestedReviewer }) {
  const displayName = suggestedReviewerDisplayName(reviewer);
  const identity = (
    <span className="flex min-w-0 items-center gap-2">
      {reviewer.user ? (
        <ReviewerAvatar
          name={displayName}
          email={reviewer.user.email}
          seed={reviewer.user.uuid}
          size="sm"
        />
      ) : reviewer.github_login ? (
        <SuggestedReviewerAvatar
          githubLogin={reviewer.github_login}
          size="sm"
        />
      ) : null}
      <span className="truncate font-medium text-foreground text-xs">
        {displayName}
      </span>
    </span>
  );

  if (reviewer.user) return identity;

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            className="min-w-0 cursor-help text-left opacity-70"
          />
        }
      >
        {identity}
      </TooltipTrigger>
      <TooltipContent side="top">{UNLINKED_REVIEWER_MESSAGE}</TooltipContent>
    </Tooltip>
  );
}

function ReviewerSourceBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex max-w-32 shrink-0 items-center justify-center rounded-full bg-fill-hover px-1.5 py-0.5 text-right font-medium text-[10px] text-foreground leading-tight">
      {label}
    </span>
  );
}

function ScoutSourceBadge({ scoutNames }: { scoutNames: string[] }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={<InboxBadge className="cursor-help text-[10px]" />}
      >
        Added by scout
      </TooltipTrigger>
      <TooltipContent side="top" className="flex-col items-start">
        {scoutNames.map((scoutName) => (
          <span key={scoutName}>{scoutName}</span>
        ))}
      </TooltipContent>
    </Tooltip>
  );
}

function RemoveReviewerButton({
  reviewer,
  disabled,
  onRemove,
}: {
  reviewer: SuggestedReviewer;
  disabled: boolean;
  onRemove: (reviewer: SuggestedReviewer) => void;
}) {
  const displayName = suggestedReviewerDisplayName(reviewer);
  return (
    <Button
      type="button"
      variant="link-muted"
      size="icon-xs"
      aria-label={`Remove ${displayName}`}
      disabled={disabled}
      data-attr="inbox-report-remove-reviewer"
      className="opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
      onClick={() => onRemove(reviewer)}
    >
      <XIcon size={12} />
    </Button>
  );
}

function SuggestedReviewerPerson({
  reviewer,
  disabled,
  onRemove,
}: {
  reviewer: SuggestedReviewer;
  disabled: boolean;
  onRemove?: (reviewer: SuggestedReviewer) => void;
}) {
  const explanation = suggestedReviewerExplanation(reviewer);
  const sourceLabel = suggestedReviewerSourceLabel(reviewer);
  return (
    <div className="group grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-x-2 gap-y-1 rounded-sm px-1.5 py-1.5 hover:bg-fill-hover">
      <ReviewerIdentity reviewer={reviewer} />
      {isScoutSuggestedReviewer(reviewer) ? (
        <ScoutSourceBadge scoutNames={[sourceLabel]} />
      ) : (
        <ReviewerSourceBadge label={sourceLabel} />
      )}
      {onRemove ? (
        <RemoveReviewerButton
          reviewer={reviewer}
          disabled={disabled}
          onRemove={onRemove}
        />
      ) : null}
      {explanation ? (
        <p
          className={`col-span-3 m-0 min-w-0 break-words text-muted-foreground text-xs leading-snug ${reviewer.user ? "" : "opacity-70"}`}
        >
          {explanation}
        </p>
      ) : null}
    </div>
  );
}

function SuggestedReviewerReasonGroup({
  reviewers,
  reason,
  disabled,
  onRemove,
}: {
  reviewers: SuggestedReviewer[];
  reason: string;
  disabled: boolean;
  onRemove?: (reviewer: SuggestedReviewer) => void;
}) {
  const scoutNames = new Set<string>();
  const otherSourceLabels = new Set<string>();
  for (const reviewer of reviewers) {
    const sourceLabel = suggestedReviewerSourceLabel(reviewer);
    if (isScoutSuggestedReviewer(reviewer)) scoutNames.add(sourceLabel);
    else otherSourceLabels.add(sourceLabel);
  }

  return (
    <div className="overflow-hidden rounded-sm border border-border bg-muted/40">
      <div className="flex flex-col p-1">
        {reviewers.map((reviewer) => (
          <div
            key={
              reviewer.user?.uuid ??
              reviewer.user_uuid ??
              reviewer.github_login ??
              suggestedReviewerDisplayName(reviewer)
            }
            className="group flex min-w-0 items-center gap-2 rounded-sm py-0.5 pr-0.5 pl-1.5 hover:bg-fill-hover"
          >
            <div className="min-w-0 flex-1">
              <ReviewerIdentity reviewer={reviewer} />
            </div>
            {onRemove ? (
              <RemoveReviewerButton
                reviewer={reviewer}
                disabled={disabled}
                onRemove={onRemove}
              />
            ) : null}
          </div>
        ))}
      </div>
      <div className="flow-root min-w-0 border-border border-t px-2.5 py-2">
        <div className="float-right ml-2 flex min-w-0 flex-wrap justify-end gap-1">
          {scoutNames.size > 0 ? (
            <ScoutSourceBadge scoutNames={[...scoutNames]} />
          ) : null}
          {[...otherSourceLabels].map((sourceLabel) => (
            <ReviewerSourceBadge key={sourceLabel} label={sourceLabel} />
          ))}
        </div>
        <p className="m-0 min-w-0 break-words text-muted-foreground text-xs leading-snug">
          {reason}
        </p>
      </div>
    </div>
  );
}

export function SuggestedReviewersList({
  reviewers,
  disabled,
  onRemove,
}: {
  reviewers: SuggestedReviewer[];
  disabled: boolean;
  onRemove?: (reviewer: SuggestedReviewer) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const items = buildSuggestedReviewerItems(reviewers);
  const visibleItems = showAll
    ? items
    : items.slice(0, MAX_VISIBLE_SUGGESTIONS);

  return (
    <div className="flex flex-col gap-1.5">
      {visibleItems.map((item) =>
        item.kind === "reason-group" ? (
          <SuggestedReviewerReasonGroup
            key={item.key}
            reviewers={item.reviewers}
            reason={item.reason}
            disabled={disabled}
            onRemove={onRemove}
          />
        ) : (
          <SuggestedReviewerPerson
            key={item.key}
            reviewer={item.reviewer}
            disabled={disabled}
            onRemove={onRemove}
          />
        ),
      )}
      {items.length > MAX_VISIBLE_SUGGESTIONS ? (
        <Button
          type="button"
          variant="link-muted"
          size="xs"
          className="w-full"
          onClick={() => setShowAll((visible) => !visible)}
        >
          {showAll ? "Show less" : `Show all (${items.length})`}
        </Button>
      ) : null}
    </div>
  );
}
