import {
  getPrVisualConfig,
  type PrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { Button, Flex, Spinner, Text } from "@radix-ui/themes";
import { getPrVisualIcon } from "../prIcon";

interface PRBadgeLinkProps {
  prUrl: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  isPrPending?: boolean;
  /**
   * When true, flatten the right edge so a dropdown trigger button can sit
   * flush against this badge (used by TaskActionsMenu's combined control).
   */
  attachedRight?: boolean;
  /**
   * Compact pill matching the other badges in the command-center cell header
   * (text-[10px], small padding). Renders as a plain anchor instead of a
   * Radix Button.
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
  attachedRight = false,
  compact = false,
  otherCount = 0,
}: PRBadgeLinkProps) {
  const config = getPrVisualConfig(prState, merged, draft);
  const PrIcon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(prUrl);

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
          <Spinner size="1" />
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
      size="1"
      variant="soft"
      color={config.color}
      asChild
      className={attachedRight ? "rounded-r-none" : undefined}
    >
      <a
        href={prUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        title={stackTitle}
      >
        <Flex align="center" gap="2">
          {isPrPending ? (
            <Spinner size="1" />
          ) : (
            <PrIcon size={12} weight="bold" />
          )}
          {/* 12px matches the quill size="sm" buttons this badge sits beside
              in the task header (the app bumps Radix --font-size-1 to 13px). */}
          <Text size="1" className="text-[12px]">
            {config.label}
            {prNumber && ` #${prNumber}`}
          </Text>
          {otherCount > 0 && (
            <Flex
              align="center"
              className={`border-l pl-2 ${COUNT_DIVIDER_CLASSES[config.color]}`}
            >
              <Text size="1" className="text-[12px]">
                {totalCount}
              </Text>
            </Flex>
          )}
        </Flex>
      </a>
    </Button>
  );
}
