import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ChannelItemHoverCard } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { WorkRowSurface } from "@posthog/ui/features/canvas/components/work/WorkRowSurface";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";

/**
 * One line in the Work column's Recent list: what state it is in, what it is
 * called, and — once the pointer is on it — when you last touched it.
 *
 * The marks are the session list's own (`taskDot`), so a row here and the same
 * session in its space say the same thing about it.
 */
export function WorkItemRow({
  item,
  menu,
  isActive,
  onOpen,
}: {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
  isActive: boolean;
  onOpen: () => void;
}) {
  // No PR lookup: that is a query into git per row, and this list spans every
  // space the viewer has.
  const status = useChannelTaskStatus(item, { withPrStatus: false });
  // The session lists' own overflow behaviour: a name too long to fit tickers
  // under the pointer rather than stopping at an ellipsis nobody can read past.
  const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();
  return (
    <TaskRowContextMenu menu={menu}>
      <ChannelItemHoverCard item={item} menu={menu}>
        <WorkRowSurface
          optionValue={item.key}
          data-selected={isActive || undefined}
          onClick={onOpen}
          {...hoverProps}
          {...focusProps}
        >
          <span className="flex size-3.5 shrink-0 items-center justify-center">
            {item.kind === "canvas" ? (
              iconForTemplate(item.templateId ?? "freeform", {
                size: 13,
                className: "text-violet-9",
              })
            ) : (
              <TaskStatusDot dot={taskDot(status ?? {})} hitArea="row" />
            )}
          </span>
          <OverflowTickerText reveal={reveal} className="flex-1">
            {item.title}
          </OverflowTickerText>
          <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums opacity-0 transition-opacity group-hover/button:opacity-100 group-data-selected/button:opacity-100">
            {formatRelativeTimeShort(item.ts)}
          </span>
        </WorkRowSurface>
      </ChannelItemHoverCard>
    </TaskRowContextMenu>
  );
}
