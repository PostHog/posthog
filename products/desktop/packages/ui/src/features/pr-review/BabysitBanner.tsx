import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { Button, Spinner } from "@posthog/quill";
import { useApproveBabysit, useBabysitAttention } from "./useBabysitAttention";

interface BabysitBannerProps {
  taskId: string | undefined;
  runId: string | undefined;
  prUrl: string;
}

/**
 * The consent card for "ask" babysit mode. When the run's workflow has staged
 * PR attention and is waiting for consent, this banner shows what needs
 * fixing and offers to approve the wake-up. In other modes the workflow does
 * not wait, the query returns null, and the banner renders nothing.
 */
export function BabysitBanner({ taskId, runId, prUrl }: BabysitBannerProps) {
  const attention = useBabysitAttention(taskId, runId);
  const approve = useApproveBabysit(taskId, runId);

  // Nothing staged or not in ask mode — the PR view shows CI checks as-is.
  if (!attention.data) return null;

  const attentionItems = attention.data.attention;
  const failingCount = countFailingChecks(attentionItems);
  const reviewCount = countReviewThreads(attentionItems);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-(--blue-7) bg-(--blue-2) p-3">
      <div className="flex items-start gap-2">
        <span
          className="mt-0.5 size-2 shrink-0 rounded-full bg-(--blue-9)"
          aria-hidden="true"
        />
        <div className="flex flex-col gap-1">
          <span className="font-medium text-(--blue-12) text-[13px]">
            CI needs attention
          </span>
          <span className="text-(--blue-11) text-[12px]">
            The agent can fix this. Approve to let it spend turns on failing
            checks and review comments.
            {failingCount > 0 &&
              ` ${failingCount} failing check${failingCount > 1 ? "s" : ""}.`}
            {reviewCount > 0 &&
              ` ${reviewCount} unresolved review thread${reviewCount > 1 ? "s" : ""}.`}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          disabled={approve.isPending}
          onClick={() => approve.mutate()}
        >
          {approve.isPending ? <Spinner className="size-3" /> : null}
          Approve babysitting
        </Button>
        <a
          href={prUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-(--blue-11) text-[12px] underline hover:text-(--blue-12)"
        >
          <ArrowSquareOutIcon size={12} className="mr-0.5 inline" />
          View on GitHub
        </a>
      </div>
    </div>
  );
}

function countFailingChecks(
  attention: Record<string, unknown> | undefined,
): number {
  const checks = attention?.failing_checks;
  return Array.isArray(checks) ? checks.length : 0;
}

function countReviewThreads(
  attention: Record<string, unknown> | undefined,
): number {
  const threads = attention?.review_threads;
  return Array.isArray(threads) ? threads.length : 0;
}
