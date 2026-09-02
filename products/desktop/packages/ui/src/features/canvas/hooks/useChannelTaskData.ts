import {
  deriveTaskData,
  narrowFullTask,
  type TaskSession,
} from "@posthog/core/sidebar/buildSidebarData";
import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import type { Task } from "@posthog/shared/domain-types";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useSuspendedTaskIds } from "@posthog/ui/features/suspension/useSuspendedTaskIds";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";
import { useMemo } from "react";

const EMPTY_SET: ReadonlySet<string> = new Set();
const EMPTY_MAP: ReadonlyMap<string, string> = new Map();

// Build the same `TaskData` shape the sidebar feeds into `<TaskIcon>` so a
// filed channel task renders the same status icons (needs-permission, cloud
// run status, PR state, generating, etc.) as in the sidebar/command palette.
export function useChannelTaskData(
  task: Task | undefined,
): TaskData | undefined {
  const session = useSessionForTask(task?.id);
  const workspace = useWorkspace(task?.id);
  const { pinnedTaskIds } = usePinnedTasks();
  const suspendedTaskIds = useSuspendedTaskIds();
  const { timestamps } = useTaskViewed();

  return useMemo(() => {
    if (!task) return undefined;
    const sidebarTask = narrowFullTask(task);
    return deriveTaskData(sidebarTask, {
      session: session as TaskSession | undefined,
      workspace: workspace ?? undefined,
      timestamp: timestamps[task.id],
      pinnedIds: pinnedTaskIds,
      suspendedIds: suspendedTaskIds,
      slackTaskIds: EMPTY_SET,
      slackThreadUrlByTaskId: EMPTY_MAP,
    });
  }, [task, session, workspace, timestamps, pinnedTaskIds, suspendedTaskIds]);
}
