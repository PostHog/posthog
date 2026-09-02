import { isNotification, POSTHOG_NOTIFICATIONS } from "./acpNotifications";
import type {
  PortableSessionNotification,
  PortableSessionToolCallStatus,
  PortableSessionUpdateEvent,
} from "./portableSessionEvents";

export type SessionActivityPhase = "idle" | "connecting" | "working";

export type SessionActivityEvent =
  | PortableSessionUpdateEvent
  | {
      type: "acp_message";
      ts: number;
      message: unknown;
    };

export interface SessionActivityState {
  isPromptPending?: boolean;
  awaitingAgentOutput?: boolean;
  terminalStatus?: "failed" | "completed";
  events?: readonly SessionActivityEvent[];
}

function isQuestionNotification(
  notification: PortableSessionNotification,
): boolean {
  const update = notification.update;
  if (!update) return false;

  const rawToolName = update._meta?.claudeCode?.toolName;
  if (typeof rawToolName === "string" && /question/i.test(rawToolName)) {
    return true;
  }

  const rawInput = update.rawInput;
  if (!rawInput) return false;
  if (Array.isArray(rawInput.questions)) return true;

  const nestedInput = rawInput.input;
  return (
    typeof nestedInput === "object" &&
    nestedInput !== null &&
    Array.isArray((nestedInput as { questions?: unknown }).questions)
  );
}

function isPendingQuestionStatus(
  status: PortableSessionToolCallStatus | undefined,
): boolean {
  return status === null || status === "pending" || status === "in_progress";
}

export function isSessionAwaitingUserInput(
  events: readonly SessionActivityEvent[] = [],
): boolean {
  let awaitingUserInput = false;
  const questionStatuses = new Map<
    string,
    PortableSessionToolCallStatus | undefined
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
        sessionUpdate === "tool_call" ||
        sessionUpdate === "tool_call_update"
      ) {
        const toolCallId = update?.toolCallId;
        const isKnownQuestion = toolCallId
          ? questionStatuses.has(toolCallId)
          : false;
        if (!isKnownQuestion && !isQuestionNotification(event.notification)) {
          continue;
        }

        questionStatuses.set(
          toolCallId ?? `question-${event.ts}`,
          update?.status,
        );
        awaitingUserInput = [...questionStatuses.values()].some(
          isPendingQuestionStatus,
        );
      }

      continue;
    }

    const method =
      typeof event.message === "object" &&
      event.message !== null &&
      "method" in event.message &&
      typeof event.message.method === "string"
        ? event.message.method
        : undefined;
    if (method === "_posthog/awaiting_user_input") {
      awaitingUserInput = true;
      continue;
    }

    if (
      isNotification(method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE) ||
      isNotification(method, POSTHOG_NOTIFICATIONS.TASK_COMPLETE) ||
      isNotification(method, POSTHOG_NOTIFICATIONS.ERROR)
    ) {
      awaitingUserInput = false;
      questionStatuses.clear();
    }
  }

  return awaitingUserInput;
}

export function countUserMessages(
  events: readonly SessionActivityEvent[] = [],
): number {
  return events.filter(
    (event) =>
      event.type === "session_update" &&
      event.notification.update?.sessionUpdate === "user_message_chunk",
  ).length;
}

export function getSessionActivityPhase(args: {
  retrying: boolean;
  session?: SessionActivityState | null;
}): SessionActivityPhase {
  const { retrying, session } = args;

  if (retrying) return "connecting";
  if (!session?.isPromptPending || session.terminalStatus) return "idle";
  if (isSessionAwaitingUserInput(session.events)) return "idle";
  return session.awaitingAgentOutput ? "connecting" : "working";
}
