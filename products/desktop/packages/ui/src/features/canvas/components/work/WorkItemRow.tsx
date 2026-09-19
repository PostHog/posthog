import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { cn } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ChannelItemHoverCard } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";

/**
 * One line in the Work column's Recent list: what state it is in, what it is
 * called, and when you last touched it.
 *
 * Deliberately not `ChannelItemRow`. That row belongs to a space's own list,
 * where a title clips and tickers on hover and a trailing badge stack says
 * which space facts apply. Here the list crosses every space and is read at a
 * glance, so a name that does not fit ends in an ellipsis and the only trailing
 * mark is its age.
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
  return (
    <TaskRowContextMenu menu={menu}>
      <ChannelItemHoverCard item={item} menu={menu}>
        <button
          type="button"
          onClick={onOpen}
          data-selected={isActive || undefined}
          className={cn(
            "group flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-[13px] transition-colors",
            "text-muted-foreground hover:bg-fill-hover hover:text-foreground",
            "data-selected:bg-fill-selected data-selected:text-foreground",
          )}
        >
          <span className="flex size-3.5 shrink-0 items-center justify-center">
            {item.kind === "canvas" ? (
              iconForTemplate(item.templateId ?? "freeform", {
                size: 12,
                className: "text-violet-9",
              })
            ) : (
              <TaskStatusDot dot={taskDot(status ?? {})} hitArea="row" />
            )}
          </span>
          <span className="min-w-0 flex-1 truncate">{item.title}</span>
          <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums opacity-0 transition-opacity group-hover:opacity-100 group-data-selected:opacity-100">
            {formatRelativeTimeShort(item.ts)}
          </span>
        </button>
      </ChannelItemHoverCard>
    </TaskRowContextMenu>
  );
}
