import { SessionConnectingError } from "@posthog/core/sessions/sessionErrors";
import { sessionStoreSetters } from "@posthog/ui/features/sessions/sessionStore";
import { toast } from "@posthog/ui/primitives/toast";

const CONNECTING_TOAST_DELAY_MS = 20_000;
const connectingToastTimers = new Map<string, ReturnType<typeof setTimeout>>();
const shownConnectingToastTaskIds = new Set<string>();

function getSessionKey(taskId: string, startedAt: number): string {
  return `${taskId}-${startedAt}`;
}

function showConnectingToast(taskId: string, sessionKey: string): void {
  if (shownConnectingToastTaskIds.has(sessionKey)) return;
  shownConnectingToastTaskIds.add(sessionKey);
  toast.error("Session is still connecting.", {
    id: `session-connecting-${sessionKey}`,
  });
}

function showDelayedConnectingToast(taskId: string): void {
  const session = sessionStoreSetters.getSessionByTaskId(taskId);
  if (session?.status !== "connecting") return;

  const sessionKey = getSessionKey(taskId, session.startedAt);
  if (
    shownConnectingToastTaskIds.has(sessionKey) ||
    connectingToastTimers.has(sessionKey)
  ) {
    return;
  }

  const delay = Math.max(
    0,
    session.startedAt + CONNECTING_TOAST_DELAY_MS - Date.now(),
  );
  if (delay === 0) {
    showConnectingToast(taskId, sessionKey);
    return;
  }

  connectingToastTimers.set(
    sessionKey,
    setTimeout(() => {
      connectingToastTimers.delete(sessionKey);
      if (
        sessionStoreSetters.getSessionByTaskId(taskId)?.status === "connecting" &&
        getSessionKey(taskId, session.startedAt) === sessionKey
      ) {
        showConnectingToast(taskId, sessionKey);
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
