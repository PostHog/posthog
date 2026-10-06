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
  spaceName: string | undefined;
  channelId: string | undefined;
  isActive: boolean;
  currentUserUuid: string | undefined;
  onOpen: () => void;
}) {
  const status = useChannelTaskStatus(item, { withPrStatus: false });
  const subtitle = useChannelItemMetadata(item, spaceName);
  const { reveal, hoverProps, focusProps } = useOverflowTickerReveal();
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

          <RowPresence item={item} currentUserUuid={currentUserUuid} />
          <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums opacity-0 transition-opacity group-hover/button:opacity-100 group-data-selected/button:opacity-100">
            {formatRelativeTimeShort(item.ts)}
          </span>
        </WorkRowSurface>
      </ChannelItemHoverCard>
    </TaskRowContextMenu>
  );
}
