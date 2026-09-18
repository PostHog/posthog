import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { placeTaskInCommandCenter } from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback, useEffect, useRef } from "react";

/**
 * What an activity row can do to its task, from the definition the space's own
 * lists and feed cards use, so the actions can't drift between them.
 *
 * Three items stay behind. Rename edits a row in place and the feed has no
 * inline editor; hand off and analysis need the task itself, which an activity
 * row doesn't carry — it holds one update about a task, not the task.
 *
 * Built once for the feed rather than per row: each hook here is a mutation or
 * a store subscription, and the feed shows a page of rows at a time.
 */
export function useActivityTaskMenu(): (
  item: TaskActivityItem,
) => TaskRowMenuProps {
  const { pinnedTaskIds, togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask();
  const cells = useCommandCenterStore((state) => state.cells);

  // `archiveTask` is a new function every render, so it goes through a ref to
  // keep the builder below stable while still calling the current one. The ref
  // is written after the commit, not during the render, because a render can be
  // thrown away and a row only reads this from an event handler.
  const archiveRef = useRef(archiveTask);
  useEffect(() => {
    archiveRef.current = archiveTask;
  });

  return useCallback(
    (item) => ({
      kind: "task",
      id: item.taskId,
      title: item.taskTitle,
      isPinned: pinnedTaskIds.has(item.taskId),
      // Ticks the space the task is already filed to, inside "File to…".
      channelId: item.channelId ?? undefined,
      onAddToCommandCenter: cells.includes(item.taskId)
        ? undefined
        : () => placeTaskInCommandCenter(item.taskId, item.taskTitle),
      onTogglePin: () => {
        togglePin(item.taskId).catch(() => {
          toast.error("Couldn't update pin");
        });
      },
      onArchive: () => {
        archiveRef.current({ taskId: item.taskId }).catch(() => {
          toast.error("Couldn't archive task");
        });
      },
    }),
    [cells, pinnedTaskIds, togglePin],
  );
}
