import type { Task } from "@posthog/shared/domain-types";
import { TaskHeaderActions } from "@posthog/ui/features/task-detail/components/TaskHeaderActions";
import { useHeaderStore } from "@posthog/ui/shell/headerStore";

/**
 * The title row above the content pane: whatever the screen below pushed into
 * the header store, plus the session's actions.
 *
 * It subscribes to that store itself rather than letting the layout do it. The
 * layout renders the screen that writes the store, so a subscription up there
 * makes every title change re-render the writer — a loop waiting for one
 * unstable value inside it. Reading it here, the writes land on a leaf.
 *
 * Renders nothing when there is neither a title nor actions to carry.
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
