import type {
  SessionEvent,
  SessionNotification,
  TerminalStatus,
} from "../types";

export type SessionActivityPhase = "idle" | "connecting" | "working";

interface SessionActivityState {
  isPromptPending?: boolean;
  awaitingAgentOutput?: boolean;
  terminalStatus?: TerminalStatus;
  events?: SessionEvent[];
}

function isQuestionNotification(notification: SessionNotification): boolean {
  const update = notification.update;
  if (!update) return false;

  const rawToolName = update._meta?.claudeCode?.toolName;
  if (typeof rawToolName === "string" && /question/i.test(rawToolName)) {
    return true;
  }

  const rawInput = update.rawInput;
  if (!rawInput) return false;

  if (Array.isArray(rawInput.questions)) {
    return true;
  }

  const nestedInput = rawInput.input;
  return (
    typeof nestedInput === "object" &&
    nestedInput !== null &&
    Array.isArray((nestedInput as { questions?: unknown }).questions)
  );
}

function isPendingQuestionStatus(
  status?: "pending" | "in_progress" | "completed" | "failed" | null,
): boolean {
  return status === null || status === "pending" || status === "in_progress";
}

export function isSessionAwaitingUserInput(
  events: SessionEvent[] = [],
): boolean {
  let awaitingUserInput = false;
  const questionStatuses = new Map<
    string,
    "pending" | "in_progress" | "completed" | "failed" | null | undefined
  >();

  for (const event of events) {
    if (event.type === "session_update") {
      const update = event.notification.update;
      const sessionUpdate = update?.sessionUpdate;

      if (sessionUpdate === "user_message_chunk") {
        awaitingUserInput = false;
        questionStatuses.clear();
        continue;
      }

      if (
        (sessionUpdate === "tool_call" ||
          sessionUpdate === "tool_call_update") &&
        isQuestionNotification(event.notification)
      ) {
        questionStatuses.set(
          update?.toolCallId ?? `question-${event.ts}`,
          update?.status,
        );
        awaitingUserInput = [...questionStatuses.values()].some((status) =>
          isPendingQuestionStatus(status),
        );
      }

      continue;
    }

    const method =
      event.message && typeof event.message === "object"
        ? (event.message as { method?: string }).method
        : undefined;

    if (method === "_posthog/awaiting_user_input") {
      awaitingUserInput = true;
      continue;
    }

    if (
      method === "_posthog/turn_complete" ||
      method === "_posthog/task_complete" ||
      method === "_posthog/error"
    ) {
      awaitingUserInput = false;
      questionStatuses.clear();
    }
  }

  return awaitingUserInput;
}

export function countUserMessages(events: SessionEvent[] = []): number {
  return events.filter(
    (e) =>
      e.type === "session_update" &&
      e.notification.update?.sessionUpdate === "user_message_chunk",
  ).length;
}

export function getSessionActivityPhase(args: {
  retrying: boolean;
  session?: SessionActivityState | null;
}): SessionActivityPhase {
  const { retrying, session } = args;

  if (retrying) {
    return "connecting";
  }

  if (!session?.isPromptPending || session.terminalStatus) {
    return "idle";
  }

  if (isSessionAwaitingUserInput(session.events)) {
    return "idle";
  }

  return session.awaitingAgentOutput ? "connecting" : "working";
}
