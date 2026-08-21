import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { Button, cn, Spinner } from "@posthog/quill";
import { getPrVisualIcon } from "../prIcon";
import {
  PR_TONE_BORDER,
  PR_TONE_FILL_COMPACT,
  prBadgeToneProps,
} from "../prTone";

interface PRBadgeLinkProps {
  prUrl: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  isPrPending?: boolean;
  /**
   * Compact pill matching the other badges in the command-center cell header
   * (text-[10px], small padding). Renders as a plain anchor instead of a
   * button.
   */
  compact?: boolean;
  /**
   * How many further PRs the task has beyond this one — rendered as a "+N"
   * suffix so multi-repo tasks signal their other PRs at a glance.
   */
  otherCount?: number;
}

/**
 * The colored "open this PR on GitHub" badge — styled by the PR's lifecycle
 * state (open / draft / closed / merged) and rendered as an external anchor.
 * Shared between the task header (TaskActionsMenu) and the command center
 * cell header.
 */
export function PRBadgeLink({
  prUrl,
  prState,
  merged,
  draft,
  isPrPending = false,
  compact = false,
  otherCount = 0,
}: PRBadgeLinkProps) {
  const config = getPrVisualConfig(prState, merged, draft);
  const PrIcon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(prUrl);
  const tone = prBadgeToneProps(config);

  const totalCount = otherCount + 1;
  const stackTitle =
    otherCount > 0 ? `${totalCount} pull requests on this task` : undefined;

  if (compact) {
    return (
      <a
        href={prUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        title={stackTitle}
        className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] no-underline ${PR_TONE_FILL_COMPACT[config.color]}`}
      >
        {isPrPending ? (
          <Spinner className="size-2.5" />
        ) : (
          <PrIcon size={10} weight="bold" />
        )}
        <span>
          {config.label}
          {prNumber && ` #${prNumber}`}
        </span>
        {otherCount > 0 && <span className="ml-0.5">{totalCount}</span>}
      </a>
    );
  }

  return (
    <Button
      size="sm"
      // The anchor is the button, so the badge is one thing to click and one
      // thing to tab to — and inside a `ButtonGroup` it takes the group's own
      // corner treatment instead of a hand-flattened right edge.
      render={
        // biome-ignore lint/a11y/useAnchorContent: the content is the button's children, across a render prop the rule can't follow, and `aria-label` names it anyway
        <a
          href={prUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={stackTitle}
          // The label the button's own children spell out. Named here because
          // the anchor is the rendered element, and its content arrives from
          // the button around it.
          aria-label={`Open ${config.label}${prNumber ? ` #${prNumber}` : ""} on GitHub${stackTitle ? `, ${totalCount} on this task` : ""}`}
          onClick={(e) => e.stopPropagation()}
        />
      }
      variant={tone.variant}
      className={cn("no-underline", tone.className)}
    >
      {isPrPending ? <Spinner className="size-3" /> : <PrIcon weight="bold" />}
      <span>
        {config.label}
        {prNumber && ` #${prNumber}`}
      </span>
      {otherCount > 0 && (
        <span className={`border-l pl-2 ${PR_TONE_BORDER[config.color]}`}>
          {totalCount}
        </span>
      )}
    </Button>
  );
}
