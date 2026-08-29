import {
  CaretDownIcon,
  CheckCircleIcon,
  CheckIcon,
  CircleNotchIcon,
  GitMergeIcon,
  MinusCircleIcon,
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
import { PrChecksSection } from "./PrChecksSection";
import { useApprovePr } from "./useApprovePr";
import { useMarkPrReady } from "./useMarkPrReady";
import { useMergePr } from "./useMergePr";
import { usePrMergeGate } from "./usePrMergeGate";
import { useReopenPr } from "./useReopenPr";

const MERGE_METHODS: PrMergeMethod[] = ["merge", "squash", "rebase"];

const MERGE_METHOD_LABELS: Record<PrMergeMethod, string> = {
  merge: "Merge pull request",
  squash: "Squash and merge",
  rebase: "Rebase and merge",
};

// The decision buttons are the page's one ask, so they render a size up from
// the surrounding chrome.
const BIG_BUTTON = "h-9 gap-2 px-4 text-[13px]";

interface PrDecisionBlockProps {
  prUrl: string;
}

/**
 * The report's ask, front and center: one distilled line on where the PR
 * stands, and the approve / merge actions at full size. Replaces the CI-checks
 * card and the review row that used to sit under Comments — the per-check list
 * stays reachable behind the status line for debugging.
 */
export function PrDecisionBlock({ prUrl }: PrDecisionBlockProps) {
  const gate = usePrMergeGate(prUrl);
  const approve = useApprovePr(prUrl);
  const merge = useMergePr(prUrl);
  const markReady = useMarkPrReady(prUrl);
  const reopen = useReopenPr(prUrl);
  const [method, setMethod] = useState<PrMergeMethod>("merge");
  const [checksOpen, setChecksOpen] = useState(false);

  if (gate.merged) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-(--gray-5) bg-(--gray-2) px-4 py-3 text-[13px] text-gray-11">
        <GitMergeIcon size={16} className="text-(--purple-9)" />
        This pull request has been merged.
      </div>
    );
  }

  if (gate.closed) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-(--gray-5) bg-(--gray-2) px-4 py-3 text-[13px] text-gray-11">
        <XCircleIcon size={16} className="text-(--red-9)" />
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
      </div>
    );
  }

  const approved = approve.isSuccess && approve.data.success;
  const approveDisabled = !gate.info || approve.isPending || approved;
  const mergeDisabled =
    !gate.info ||
    gate.draft ||
    merge.isPending ||
    !gate.checksLoaded ||
    gate.mergeBlockedReason !== null;

  // One distilled line replaces the per-check matrix. Failing leads because it
  // is the state that needs the user; the full list sits behind the toggle.
  const statusLine = !gate.checksLoaded ? (
    gate.checksUnavailable ? (
      <span className="flex items-center gap-1.5 text-gray-10">
        <XCircleIcon size={14} />
        Checks unavailable
      </span>
    ) : (
      <span className="flex items-center gap-1.5 text-gray-10">
        <Spinner />
        Loading checks…
      </span>
    )
  ) : gate.failedChecks > 0 ? (
    <span className="flex items-center gap-1.5 text-(--red-11)">
      <XCircleIcon size={14} />
      {gate.failedChecks} check{gate.failedChecks === 1 ? "" : "s"} failing
    </span>
  ) : gate.pendingChecks > 0 ? (
    <span className="flex items-center gap-1.5 text-(--amber-11)">
      <CircleNotchIcon size={14} className="animate-spin" />
      Checks running
    </span>
  ) : gate.totalChecks === 0 ? (
    <span className="flex items-center gap-1.5 text-gray-10">
      <MinusCircleIcon size={14} />
      No checks reported
    </span>
  ) : (
    <span className="flex items-center gap-1.5 text-(--green-11)">
      <CheckCircleIcon size={14} />
      All checks passed
    </span>
  );

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-(--gray-5) bg-(--gray-1) p-4">
      <div className="flex flex-wrap items-center gap-3 text-[13px]">
        {statusLine}
        {gate.totalChecks > 0 && (
          <button
            type="button"
            onClick={() => setChecksOpen((open) => !open)}
            className="text-[12px] text-gray-10 underline decoration-dotted underline-offset-2 transition-colors hover:text-gray-12"
          >
            {checksOpen ? "Hide checks" : `View ${gate.totalChecks} checks`}
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          type="button"
          variant="outline"
          disabled={approveDisabled}
          onClick={() => approve.mutate({ prUrl })}
          className={BIG_BUTTON}
        >
          {approve.isPending ? (
            <Spinner />
          ) : approved ? (
            <CheckCircleIcon size={15} className="text-(--green-9)" />
          ) : (
            <CheckIcon size={15} />
          )}
          {approved ? "Approved" : "Approve"}
        </Button>
        <ButtonGroup>
          <Button
            type="button"
            variant="primary"
            disabled={mergeDisabled}
            onClick={() => merge.mutate({ prUrl, method })}
            className={BIG_BUTTON}
          >
            {merge.isPending ? <Spinner /> : <GitMergeIcon size={15} />}
            {MERGE_METHOD_LABELS[method]}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  type="button"
                  variant="primary"
                  aria-label="Choose merge method"
                  disabled={mergeDisabled}
                  className="h-9"
                >
                  <CaretDownIcon size={13} />
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
        {gate.draft && (
          <>
            <span className="text-[12px] text-gray-10">
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
      </div>

      {gate.mergeBlockedReason && (
        <span className="text-(--red-11) text-[12px]">
          {gate.mergeBlockedReason}
        </span>
      )}

      {checksOpen && <PrChecksSection prUrl={prUrl} />}
    </div>
  );
}
