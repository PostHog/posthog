import { ArrowsClockwiseIcon } from "@phosphor-icons/react";
import { formatRelativeTimeShort } from "@posthog/shared";
import { IconButton, Text, Tooltip } from "@radix-ui/themes";

/**
 * "Updated Xs ago" label + a manual refresh button. Pairs with a react-query
 * `refetchInterval` (which auto-polls and pauses when the tab is unfocused);
 * this just surfaces freshness and a manual nudge. `updatedAt` is the query's
 * `dataUpdatedAt` (epoch ms; 0 before the first load).
 */
export function RefreshIndicator({
  updatedAt,
  isFetching,
  onRefresh,
  compact = false,
}: {
  updatedAt: number;
  isFetching: boolean;
  onRefresh: () => void;
  compact?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5">
      {!compact ? (
        <Text className="text-[11px] text-gray-10">
          {isFetching
            ? "updating…"
            : updatedAt
              ? `updated ${formatRelativeTimeShort(updatedAt)}`
              : ""}
        </Text>
      ) : null}
      <Tooltip content="Refresh">
        <IconButton
          size="1"
          variant="ghost"
          color="gray"
          onClick={onRefresh}
          disabled={isFetching}
          aria-label="Refresh"
        >
          <ArrowsClockwiseIcon
            size={14}
            className={isFetching ? "animate-spin" : undefined}
          />
        </IconButton>
      </Tooltip>
    </div>
  );
}
