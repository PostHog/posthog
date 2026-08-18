import {
  getPrVisualConfig,
  type PrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { Button, cn, Spinner } from "@posthog/quill";
import { getPrVisualIcon } from "../prIcon";

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

const COMPACT_COLOR_CLASSES: Record<PrVisualConfig["color"], string> = {
  gray: "bg-(--gray-3) text-(--gray-11) hover:bg-(--gray-4)",
  green: "bg-(--green-3) text-(--green-11) hover:bg-(--green-4)",
  red: "bg-(--red-3) text-(--red-11) hover:bg-(--red-4)",
  purple: "bg-(--purple-3) text-(--purple-11) hover:bg-(--purple-4)",
};

/**
 * The PR's lifecycle colour, as classes for a quill button. quill's variants
 * are one neutral palette by design, and this badge's whole job is to say
 * merged from closed from open at a glance — so the tint comes from the Radix
 * token layer, which is what the app's colour scales live in anyway.
 */
const PR_BADGE_TONE_CLASSES: Record<PrVisualConfig["color"], string> = {
  gray: "bg-(--gray-3) text-(--gray-11) not-disabled:hover:bg-(--gray-4) not-disabled:hover:text-(--gray-12)",
  green:
    "bg-(--green-3) text-(--green-11) not-disabled:hover:bg-(--green-4) not-disabled:hover:text-(--green-12)",
  red: "bg-(--red-3) text-(--red-11) not-disabled:hover:bg-(--red-4) not-disabled:hover:text-(--red-12)",
  purple:
    "bg-(--purple-3) text-(--purple-11) not-disabled:hover:bg-(--purple-4) not-disabled:hover:text-(--purple-12)",
};

/**
 * How a badge wears its lifecycle state, as props for a quill button. A solid
 * state takes quill's own primary; the rest take their tint.
 *
 * Exported because the dropdown trigger that sits beside the badge in a
 * `ButtonGroup` has to wear the same thing, or the group reads as two controls.
 */
export function prBadgeToneProps(config: PrVisualConfig): {
  variant?: "primary";
  className?: string;
} {
  if (config.solid) return { variant: "primary" };
  return { className: PR_BADGE_TONE_CLASSES[config.color] };
}

// Divider ahead of the PR-count segment, tinted to the badge's own color.
const COUNT_DIVIDER_CLASSES: Record<PrVisualConfig["color"], string> = {
  gray: "border-(--gray-a6)",
  green: "border-(--green-a6)",
  red: "border-(--red-a6)",
  purple: "border-(--purple-a6)",
};

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
        className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] no-underline ${COMPACT_COLOR_CLASSES[config.color]}`}
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
        <span
          className={`border-l pl-2 ${COUNT_DIVIDER_CLASSES[config.color]}`}
        >
          {totalCount}
        </span>
      )}
    </Button>
  );
}
