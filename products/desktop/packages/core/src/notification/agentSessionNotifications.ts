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
    };

export interface AgentSessionNotifier {
  notify(notification: AgentSessionNotification): void;
}

export const AGENT_SESSION_NOTIFIER = Symbol.for(
  "posthog.notification.agentSessionNotifier",
);
