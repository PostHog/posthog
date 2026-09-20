import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { cn } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { writeCanvasDragData } from "@posthog/ui/features/canvas/canvasDrag";
import { ChannelItemHoverCard } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { RowPresence } from "@posthog/ui/features/canvas/components/ChannelItemPresence";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  TaskRowContextMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { WorkRowSurface } from "@posthog/ui/features/canvas/components/work/WorkRowSurface";
import { useChannelItemMetadata } from "@posthog/ui/features/canvas/hooks/useChannelItemFacts";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { writeTaskDragData } from "@posthog/ui/features/sidebar/taskDrag";
import {
  OverflowTickerText,
  useOverflowTickerReveal,
} from "@posthog/ui/primitives/OverflowTickerText";
import { type DragEvent, useCallback } from "react";

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
  spaceName,
  channelId,
  isActive,
  currentUserUuid,
  onOpen,
}: {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
  /** The list crosses every space, so a row can say which one it is in. */
  spaceName: string | undefined;
  /** Travels with a dragged canvas, which is filed to a space. */
  channelId: string | undefined;
  isActive: boolean;
  /** So a face can say "you" rather than name you to yourself. */
  currentUserUuid: string | undefined;
  onOpen: () => void;
}) {
  // No PR lookup: that is a query into git per row, and this list spans every
  // space the viewer has.
  const status = useChannelTaskStatus(item, { withPrStatus: false });
  // Whatever the list appearance settings ask each row to carry.
  const subtitle = useChannelItemMetadata(item, spaceName);
  // The session lists' own overflow behaviour: a name too long to fit tickers
  // under the pointer rather than stopping at an ellipsis nobody can read past.
  const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();
  // A row is a thing you can drop into a tile or the command centre, and it
  // carries the same payload the space lists' rows do — the drop targets read
  // one format, so a row writing another is simply not droppable.
  const handleDragStart = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (item.kind === "canvas") {
        writeCanvasDragData(event.dataTransfer, item.id, {
          name: item.title,
          channelId: channelId ?? null,
        });
        event.dataTransfer.effectAllowed = "copy";
        return;
      }
      writeTaskDragData(event.dataTransfer, item.id);
      // Both: a tile asks for `copy` and the pinned run asks for `move`, and a
      // source permitting only one resolves the other pairing to no drop.
      event.dataTransfer.effectAllowed = "copyMove";
    },
    [channelId, item.id, item.kind, item.title],
  );
  return (
    <TaskRowContextMenu menu={menu}>
      <ChannelItemHoverCard item={item} menu={menu}>
        <WorkRowSurface
          optionValue={item.key}
          data-selected={isActive || undefined}
          onClick={onOpen}
          draggable
          onDragStart={handleDragStart}
          className={subtitle ? "h-auto py-1" : undefined}
          {...hoverProps}
          {...focusProps}
        >
          <span
            className={cn(
              "flex size-3.5 shrink-0 items-center justify-center",
              subtitle && "self-start pt-0.5",
            )}
          >
            {item.kind === "canvas" ? (
              iconForTemplate(item.templateId ?? "freeform", {
                size: 13,
                className: "text-violet-9",
              })
            ) : (
              <TaskStatusDot dot={taskDot(status ?? {})} hitArea="row" />
            )}
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <OverflowTickerText reveal={reveal}>
              {item.title}
            </OverflowTickerText>
            {subtitle && (
              <span className="truncate text-muted-foreground/70 text-xxs group-data-selected/button:text-muted-foreground">
                {subtitle}
              </span>
            )}
          </span>
          {/* Who is here, ahead of the age: presence is the row's most
              time-sensitive fact, and a quiet row shows none of it. */}
          <RowPresence item={item} currentUserUuid={currentUserUuid} />
          <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums opacity-0 transition-opacity group-hover/button:opacity-100 group-data-selected/button:opacity-100">
            {formatRelativeTimeShort(item.ts)}
          </span>
        </WorkRowSurface>
      </ChannelItemHoverCard>
    </TaskRowContextMenu>
  );
}
