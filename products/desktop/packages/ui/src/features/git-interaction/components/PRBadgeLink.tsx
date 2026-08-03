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
}

const COMPACT_COLOR_CLASSES: Record<PrVisualConfig["color"], string> = {
  gray: "bg-(--gray-3) text-(--gray-11) hover:bg-(--gray-4)",
  green: "bg-(--green-3) text-(--green-11) hover:bg-(--green-4)",
  red: "bg-(--red-3) text-(--red-11) hover:bg-(--red-4)",
  purple: "bg-(--purple-3) text-(--purple-11) hover:bg-(--purple-4)",
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
}: PRBadgeLinkProps) {
  const config = getPrVisualConfig(prState, merged, draft);
  const PrIcon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(prUrl);

  if (compact) {
    return (
      <a
        href={prUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
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
      >
        <Flex align="center" gap="2">
          {isPrPending ? (
            <Spinner size="1" />
          ) : (
            <PrIcon size={12} weight="bold" />
          )}
          <Text size="1">
            {config.label}
            {prNumber && ` #${prNumber}`}
          </Text>
        </Flex>
      </a>
    </Button>
  );
}
