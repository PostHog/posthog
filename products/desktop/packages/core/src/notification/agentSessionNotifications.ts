import type { TaskNotificationParams } from "../sessions/schemas";

export type AgentSessionNotification =
  | {
      kind: "turn_completed";
      taskId: string;
      taskTitle: string;
      stopReason: string;
      durationMs?: number;
      isTaskAuthor?: boolean;
      agentSpoke?: boolean;
    }
  | {
      kind: "needs_input";
      taskId: string;
      taskTitle: string;
      isTaskAuthor?: boolean;
      agentSpoke?: boolean;
    }
  | {
      kind: "background_task_settled";
      taskId: string;
      taskTitle: string;
      notification: TaskNotificationParams;
      isTaskAuthor?: boolean;
    }
  | {
      kind: "session_error";
      taskId: string;
      taskTitle: string;
      error: unknown;
      isTaskAuthor?: boolean;
    };

export interface AgentSessionNotifier {
  notify(notification: AgentSessionNotification): void;
}

export const AGENT_SESSION_NOTIFIER = Symbol.for(
  "posthog.notification.agentSessionNotifier",
);
