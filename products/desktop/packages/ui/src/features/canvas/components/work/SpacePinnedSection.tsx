import { cn } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { SideColumnHeading } from "@posthog/ui/features/canvas/components/work/SideColumnHeading";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { navigateToChannelTask } from "@posthog/ui/router/navigationBridge";
import { useMemo } from "react";

/** How many pinned rows the block keeps before it would own the column. */
const MAX_ROWS = 8;

/**
 * The sessions a space keeps at hand.
 *
 * Pinning survived the Work layout but its shelf did not — the space's own
 * list, where a Pinned group sat above the days, is gone. Canvases are not
 * here: the Canvases tab already leads with the pinned ones, and a second copy
 * would be two places to unpin from.
 */
export function SpacePinnedSection({
  channelId,
  tasks,
}: {
  channelId: string;
  /** The space's feed, already loaded by the tab around this. */
  tasks: Task[];
}) {
  const { pinnedTaskIds } = usePinnedTasks();
  const sessions = useMemo(
    () => tasks.filter((task) => pinnedTaskIds.has(task.id)),
    [tasks, pinnedTaskIds],
  );

  if (sessions.length === 0) return null;

  return (
    <section aria-label="Pinned" className="flex shrink-0 flex-col">
      <SideColumnHeading>Pinned</SideColumnHeading>
      <div className="flex flex-col gap-px px-1.5 pb-2">
        {sessions.slice(0, MAX_ROWS).map((task) => (
          <button
            key={task.id}
            type="button"
            title={task.title}
            onClick={() => navigateToChannelTask(channelId, task.id)}
            className={cn(
              "flex w-full items-center gap-1.5 rounded-(--radius-2) px-2 py-1 text-left",
              "transition-colors hover:bg-fill-hover",
            )}
          >
            <span className="flex size-3.5 shrink-0 items-center justify-center">
              <TaskStatusDot dot={taskDot({})} hitArea="row" />
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px]">
              {task.title}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
