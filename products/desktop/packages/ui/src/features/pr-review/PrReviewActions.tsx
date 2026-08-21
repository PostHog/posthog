import {
  CaretDownIcon,
  CheckCircleIcon,
  CheckIcon,
  GitMergeIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import type { PrMergeMethod } from "@posthog/core/git/router-schemas";
import {
  Button,
  ButtonGroup,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Spinner,
} from "@posthog/quill";
import { useState } from "react";
import { useApprovePr } from "./useApprovePr";
import { useMarkPrReady } from "./useMarkPrReady";
import { useMergePr } from "./useMergePr";
import { usePrChecks } from "./usePrChecks";
import { usePrInfo } from "./usePrInfo";
import { useReopenPr } from "./useReopenPr";

const MERGE_METHODS: PrMergeMethod[] = ["merge", "squash", "rebase"];

const MERGE_METHOD_LABELS: Record<PrMergeMethod, string> = {
  merge: "Merge pull request",
  squash: "Squash and merge",
  rebase: "Rebase and merge",
};

interface PrReviewActionsProps {
  prUrl: string;
}

/** Approve + merge controls for a GitHub PR, mirroring the github.com merge box. */
export function PrReviewActions({ prUrl }: PrReviewActionsProps) {
  const infoQuery = usePrInfo(prUrl);
  // Shares the checks section's polling query, so the merge gate follows CI
  // live: it locks as soon as a check goes red and unlocks on a green rerun.
  const checksQuery = usePrChecks(prUrl);
  const approve = useApprovePr(prUrl);
  const merge = useMergePr(prUrl);
  const markReady = useMarkPrReady(prUrl);
  const reopen = useReopenPr(prUrl);
  const [method, setMethod] = useState<PrMergeMethod>("merge");

  const info = infoQuery.data;
  const merged = info?.merged ?? false;
  const closed = !merged && info?.state?.toLowerCase() === "closed";
  const draft = info?.draft ?? false;
  const failedChecks = (checksQuery.data ?? []).filter(
    (check) => check.bucket === "fail",
  ).length;
  const hasConflicts = info?.mergeable === false;

  if (merged || closed) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-(--gray-5) bg-(--gray-2) px-3 py-2 text-[12px] text-gray-11">
        {merged ? (
          <>
            <GitMergeIcon size={14} className="text-(--purple-9)" />
            This pull request has been merged.
          </>
        ) : (
          <>
            <XCircleIcon size={14} className="text-(--red-9)" />
            This pull request is closed.
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={reopen.isPending}
              onClick={() => reopen.mutate({ prUrl, action: "reopen" })}
              className="ml-auto gap-1.5"
            >
              {reopen.isPending && <Spinner />}
              Reopen
            </Button>
          </>
        )}
      </div>
    );
  }

  const approved = approve.isSuccess && approve.data.success;
  const approveDisabled = !info || approve.isPending || approved;
  // Failed fetch (null / error) means CI status is unknown — that must lock
  // the merge too, or a transient gh error would silently unlock red checks.
  const checksUnavailable = checksQuery.isError || checksQuery.data === null;
  // Branch protection ("blocked") is viewer-aware: it covers repos that
  // require an approving review — including the PR author, who can't approve
  // their own PR. Repos without such rules report "clean"/"unstable".
  const blockedByProtection = info?.mergeStateStatus === "blocked";
  const behindBase = info?.mergeStateStatus === "behind";
  // Same gate as github.com: red checks, conflicts, or branch protection
  // lock the merge button.
  const mergeBlockedReason = draft
    ? null // the draft branch below renders its own note + CTA
    : failedChecks > 0
      ? `${failedChecks} check${failedChecks === 1 ? " is" : "s are"} failing — merging is blocked until they pass.`
      : hasConflicts
        ? "This branch has conflicts that must be resolved before merging."
        : blockedByProtection
          ? "Branch protection blocks this merge — an approving review from another user may be required."
          : behindBase
            ? "This branch is out of date with the base branch and must be updated before merging."
            : checksUnavailable
              ? "CI status couldn't be loaded — merging is blocked until checks are known."
              : null;
  const mergeDisabled =
    !info ||
    draft ||
    merge.isPending ||
    checksQuery.data == null ||
    mergeBlockedReason !== null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={approveDisabled}
        onClick={() => approve.mutate({ prUrl })}
        className="gap-1.5"
      >
        {approve.isPending ? (
          <Spinner />
        ) : approved ? (
          <CheckCircleIcon size={13} className="text-(--green-9)" />
        ) : (
          <CheckIcon size={13} />
        )}
        {approved ? "Approved" : "Approve"}
      </Button>
      <ButtonGroup>
        <Button
          type="button"
          variant="primary"
          size="sm"
          disabled={mergeDisabled}
          onClick={() => merge.mutate({ prUrl, method })}
          className="gap-1.5"
        >
          {merge.isPending ? <Spinner /> : <GitMergeIcon size={13} />}
          {MERGE_METHOD_LABELS[method]}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                variant="primary"
                size="sm"
                aria-label="Choose merge method"
                disabled={mergeDisabled}
              >
                <CaretDownIcon size={12} />
              </Button>
            }
          />
          <DropdownMenuContent align="end" side="bottom" sideOffset={6}>
            {MERGE_METHODS.map((m) => (
              <DropdownMenuItem key={m} onClick={() => setMethod(m)}>
                {MERGE_METHOD_LABELS[m]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </ButtonGroup>
      {draft && (
        <>
          <span className="text-[11px] text-gray-10">
            Draft pull requests can't be merged.
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={markReady.isPending}
            onClick={() => markReady.mutate({ prUrl, action: "ready" })}
            className="gap-1.5"
          >
            {markReady.isPending && <Spinner />}
            Ready for review
          </Button>
        </>
      )}
      {mergeBlockedReason && (
        <span className="text-(--red-11) text-[11px]">
          {mergeBlockedReason}
        </span>
      )}
    </div>
  );
}
