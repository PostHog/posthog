import { deriveSessionViewState } from "@posthog/core/sessions/sessionViewState";
import type { Task } from "@posthog/shared/domain-types";
import { useSessionForTask } from "@posthog/ui/features/sessions/sessionStore";
import { useCwd } from "@posthog/ui/features/sidebar/useCwd";
import { useIsCloudTask } from "@posthog/ui/features/workspace/useIsCloudTask";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";

export function useSessionViewState(taskId: string, task: Task) {
  const session = useSessionForTask(taskId);
  const repoPath = useCwd(taskId) ?? null;
  const workspace = useWorkspace(taskId);
  const isCloud = useIsCloudTask(taskId, task);

  const derived = deriveSessionViewState(session, task, workspace, isCloud);

  return {
    session,
    repoPath,
    isCloud,
    ...derived,
  };
}
