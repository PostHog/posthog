import type { Task } from "@posthog/shared/domain-types";
import type { BuildResult } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { SessionFooter } from "@posthog/ui/features/sessions/components/SessionFooter";
import { SessionStartupRow } from "@posthog/ui/features/sessions/components/SessionStartupRow";
import {
  usePendingPermissionsForTask,
  useQueuedMessagesForTask,
  useSessionSelector,
} from "@posthog/ui/features/sessions/sessionStore";
import { resolvePendingPermissionVisibility } from "./pendingPermissionVisibility";

interface ChatThreadFooterProps {
  isPromptPending: boolean | null;
  promptStartedAt?: number | null;
  task?: Task;
  taskId?: string;
  footerState: Omit<BuildResult, "items">;
  hasPendingPermission?: boolean;
  currentWork?: string;
}

/**
 * The session status footer appears as the last thread item. Context usage stays in the composer toolbar.
 */
export function ChatThreadFooter({
  isPromptPending,
  promptStartedAt,
  task,
  taskId,
  footerState,
  hasPendingPermission,
  currentWork,
}: ChatThreadFooterProps) {
  const {
    lastTurnInfo,
    isCompacting,
    isClearing,
    completedToolCallCount,
    lastActivityAt,
    isBackgroundTurnActive,
  } = footerState;
  const pendingPermissions = usePendingPermissionsForTask(taskId ?? "");
  const pendingPermissionVisible = resolvePendingPermissionVisibility(
    hasPendingPermission,
    pendingPermissions.size,
  );
  const queuedCount = useQueuedMessagesForTask(taskId).length;
  const pausedDurationMs = useSessionSelector(
    taskId,
    (session) => session?.pausedDurationMs ?? 0,
  );

  return (
    <div className="pt-1">
      {taskId && task && (
        <div className="-mx-2.5 pb-1">
          <SessionStartupRow taskId={taskId} task={task} />
        </div>
      )}
      <SessionFooter
        task={task}
        isPromptPending={isPromptPending}
        promptStartedAt={promptStartedAt}
        lastGenerationDuration={
          lastTurnInfo?.isComplete
            ? Math.max(0, lastTurnInfo.durationMs - pausedDurationMs)
            : null
        }
        lastStopReason={lastTurnInfo?.stopReason}
        queuedCount={queuedCount}
        hasPendingPermission={pendingPermissionVisible}
        pausedDurationMs={pausedDurationMs}
        isCompacting={isCompacting}
        isClearing={isClearing}
        isBackgroundTurnActive={isBackgroundTurnActive}
        completedToolCallCount={completedToolCallCount}
        lastActivityAt={lastActivityAt}
        currentWork={currentWork}
      />
    </div>
  );
}
