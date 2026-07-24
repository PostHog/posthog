import type { AcpMessage } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { SessionFooter } from "@posthog/ui/features/sessions/components/SessionFooter";
import { useContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { useConversationItems } from "@posthog/ui/features/sessions/hooks/useConversationItems";
import {
  usePendingPermissionsForTask,
  useQueuedMessagesForTask,
  useSessionForTask,
} from "@posthog/ui/features/sessions/sessionStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

interface ChatThreadFooterProps {
  events: AcpMessage[];
  isPromptPending: boolean | null;
  promptStartedAt?: number | null;
  task?: Task;
  taskId?: string;
}

/**
 * The session status footer (duration / queued / context usage / diff stats) for the new chat
 * thread, rendered UNDER the composer. The legacy `ConversationView` renders the same
 * `SessionFooter` at the bottom of the thread instead; here it lives under the input.
 *
 * Re-derives the turn / usage / queue state from `events` with the same hooks `ConversationView`
 * uses — `ChatThread` runs its own `useConversationItems`, so this is a second (incremental,
 * memoized) parse pass, acceptable for a flag-gated surface. Gated behind
 * `settingsStore.useNewChatThread` at the call site.
 */
export function ChatThreadFooter({
  events,
  isPromptPending,
  promptStartedAt,
  task,
  taskId,
}: ChatThreadFooterProps) {
  const showDebugLogs = useSettingsStore((s) => s.debugLogsCloudRuns);
  const contextUsage = useContextUsage(events);
  const { lastTurnInfo, isCompacting, completedToolCallCount } =
    useConversationItems(events, isPromptPending, { showDebugLogs });
  const pendingPermissions = usePendingPermissionsForTask(taskId ?? "");
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
        hasPendingPermission={pendingPermissions.size > 0}
        pausedDurationMs={pausedDurationMs}
        isCompacting={isCompacting}
        usage={contextUsage}
        completedToolCallCount={completedToolCallCount}
      />
    </div>
  );
}
