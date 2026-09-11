import type { AcpMessage } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import type { BuildResult } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { SessionFooter } from "@posthog/ui/features/sessions/components/SessionFooter";
import { SessionStartupRow } from "@posthog/ui/features/sessions/components/SessionStartupRow";
import { useConversationItems } from "@posthog/ui/features/sessions/hooks/useConversationItems";
import {
  usePendingPermissionsForTask,
  useQueuedMessagesForTask,
  useSessionForTask,
} from "@posthog/ui/features/sessions/sessionStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { resolvePendingPermissionVisibility } from "./pendingPermissionVisibility";

interface ChatThreadFooterProps {
  events: AcpMessage[];
  isPromptPending: boolean | null;
  promptStartedAt?: number | null;
  task?: Task;
  taskId?: string;
  footerState?: Omit<BuildResult, "items">;
  hasPendingPermission?: boolean;
  currentWork?: string;
}

/**
 * The session status footer (duration / queued / diff stats), rendered as the last item in the
 * thread. Context usage sits in the composer's toolbar.
 *
 * Re-derives turn, usage, and queue state from `events` because `ChatThread` runs its own
 * incremental, memoized `useConversationItems` parse pass.
 */
export function ChatThreadFooter({
  events,
  isPromptPending,
  promptStartedAt,
  task,
  taskId,
  footerState,
  hasPendingPermission,
  currentWork,
}: ChatThreadFooterProps) {
  const showDebugLogs = useSettingsStore((s) => s.debugLogsCloudRuns);
  const eventFooterState = useConversationItems(events, isPromptPending, {
    showDebugLogs,
  });
  const lastTurnInfo =
    footerState?.lastTurnInfo ?? eventFooterState.lastTurnInfo;
  const isCompacting =
    footerState?.isCompacting ?? eventFooterState.isCompacting;
  const isClearing = footerState?.isClearing ?? eventFooterState.isClearing;
  const completedToolCallCount =
    footerState?.completedToolCallCount ??
    eventFooterState.completedToolCallCount;
  const lastActivityAt =
    footerState?.lastActivityAt ?? eventFooterState.lastActivityAt;
  const isBackgroundTurnActive =
    footerState?.isBackgroundTurnActive ??
    eventFooterState.isBackgroundTurnActive;
  const pendingPermissions = usePendingPermissionsForTask(taskId ?? "");
  const pendingPermissionVisible = resolvePendingPermissionVisibility(
    hasPendingPermission,
    pendingPermissions.size,
  );
  const queuedCount = useQueuedMessagesForTask(taskId).length;
  const session = useSessionForTask(taskId);
  const pausedDurationMs = session?.pausedDurationMs ?? 0;

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
