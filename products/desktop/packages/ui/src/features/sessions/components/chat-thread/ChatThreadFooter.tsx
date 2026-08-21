import type { AcpMessage } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import type { BuildResult } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { SessionFooter } from "@posthog/ui/features/sessions/components/SessionFooter";
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
}

/**
 * The session status footer (duration / queued / diff stats) for the new chat thread, rendered as
 * the last item in the thread. The legacy `ConversationView` renders the same `SessionFooter` the
 * same way. Context usage is not here — it sits in the composer's own toolbar.
 *
 * Re-derives the turn / usage / queue state from `events` with the same hooks the thread uses —
 * `ChatThread` runs its own `useConversationItems`, so this is a second (incremental, memoized)
 * parse pass.
 */
export function ChatThreadFooter({
  events,
  isPromptPending,
  promptStartedAt,
  task,
  taskId,
  footerState,
  hasPendingPermission,
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
      />
    </div>
  );
}
