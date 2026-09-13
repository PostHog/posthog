import { SessionConnectingError } from "@posthog/core/sessions/sessionErrors";
import { sessionStoreSetters } from "@posthog/ui/features/sessions/sessionStore";
import { toast } from "@posthog/ui/primitives/toast";

const CONNECTING_TOAST_DELAY_MS = 20_000;
const connectingToastTimers = new Map<string, ReturnType<typeof setTimeout>>();
const shownConnectingToastTaskIds = new Set<string>();

function showConnectingToast(taskId: string): void {
  if (shownConnectingToastTaskIds.has(taskId)) return;
  shownConnectingToastTaskIds.add(taskId);
  toast.error("Session is still connecting.", {
    id: `session-connecting-${taskId}`,
  });
}

function showDelayedConnectingToast(taskId: string): void {
  if (
    shownConnectingToastTaskIds.has(taskId) ||
    connectingToastTimers.has(taskId)
  ) {
    return;
  }

  const session = sessionStoreSetters.getSessionByTaskId(taskId);
  if (session?.status !== "connecting") return;

  const delay = Math.max(
    0,
    session.startedAt + CONNECTING_TOAST_DELAY_MS - Date.now(),
  );
  if (delay === 0) {
    showConnectingToast(taskId);
    return;
  }

  connectingToastTimers.set(
    taskId,
    setTimeout(() => {
      connectingToastTimers.delete(taskId);
      if (
        sessionStoreSetters.getSessionByTaskId(taskId)?.status === "connecting"
      ) {
        showConnectingToast(taskId);
      }
    }, delay),
  );
}

export function showSessionPromptError(taskId: string, error: unknown): void {
  if (error instanceof SessionConnectingError) {
    showDelayedConnectingToast(taskId);
    return;
  }

  toast.error(
    error instanceof Error
      ? error.message
      : "Failed to send your message to the agent. Please try again.",
  );
}
