import type { Task } from "@posthog/shared/domain-types";
import { useTaskStatusInput } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";

/**
 * A session tab wears the session list's status dot. Same vocabulary as the row
 * it came from, so a tab and its list entry never say different things about
 * the same session.
 */
export function TaskTabDot({ task }: { task: Task | undefined }) {
  const status = useTaskStatusInput(task);
  // No run to report yet (the task or its data hasn't landed). The dot's own
  // resting state already reads as "nothing happening", so it stands in rather
  // than a second placeholder glyph that would shift when the real one arrives.
  return <TaskStatusDot dot={taskDot(status ?? {})} />;
}
