import type { Task } from "@posthog/shared/domain-types";
import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";

/**
 * The title row above the content pane. Subscribes to the header store itself:
 * the layout renders the screen that writes that store, so subscribing up there
 * makes every title write re-render the writer.
 */
export function SpaceHeaderRow({ task }: { task?: Task }) {
  const content = useHeaderStore((s) => s.content);
  if (!content && !task) return null;

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-border border-b pr-2 pl-1">
      <div className="flex h-full min-w-0 flex-1 items-center justify-between overflow-hidden">
        {content}
      </div>
      {/* Rendered without a wrapper: the actions cap themselves at half the
          bar, and a wrapper that hugs their content resolves that percentage
          against itself, which clips them. */}
      {task && <TaskHeaderActions task={task} />}
    </div>
  );
}
