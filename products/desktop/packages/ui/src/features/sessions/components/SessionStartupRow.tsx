import type { Task } from "@posthog/shared/domain-types";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import { SessionProvisioningStatus } from "@posthog/ui/features/sessions/components/SessionProvisioningStatus";
import { SessionStartupStatus } from "@posthog/ui/features/sessions/components/SessionStartupStatus";
import { useSessionViewState } from "@posthog/ui/features/sessions/hooks/useSessionViewState";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";

export function SessionStartupRow({
  taskId,
  task,
}: {
  taskId: string;
  task: Task;
}) {
  const isProvisioning = useProvisioningStore((s) => s.activeTasks.has(taskId));
  const startupPhase = useSessionStore(
    (state) => state.startingTaskIds[taskId]?.phase,
  );
  const { isCloud, isRunning, isInitializing, hasError } = useSessionViewState(
    taskId,
    task,
  );
  const executionTarget = isCloud ? "cloud" : "local";

  if (isProvisioning) {
    return (
      <SessionProvisioningStatus
        executionTarget={executionTarget}
        taskId={taskId}
      />
    );
  }
  if (hasError || (isRunning && !isInitializing)) return null;
  return (
    <SessionStartupStatus
      executionTarget={executionTarget}
      phase={startupPhase}
      label={isInitializing ? undefined : "Connecting to agent..."}
    />
  );
}
