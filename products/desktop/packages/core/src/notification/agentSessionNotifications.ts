// The code path that raised the notification. Carried all the way to the
// notification log so a sound the user did not expect names its own origin.
export type AgentSessionNotificationTrigger =
  | "local_prompt_response"
  | "cloud_turn_complete"
  | "local_permission_request"
  | "cloud_permission_request"
  | "pi_turn_completed"
  | "pi_mcp_permission_request";

export type AgentSessionNotification =
  | {
      kind: "turn_completed";
      trigger: Extract<
        AgentSessionNotificationTrigger,
        "local_prompt_response" | "cloud_turn_complete" | "pi_turn_completed"
      >;
      taskId: string;
      // Absent on the pi runtime, which keys its sessions by task.
      taskRunId?: string;
      taskTitle: string;
      stopReason: string;
      durationMs?: number;
      isTaskAuthor?: boolean;
      agentSpoke?: boolean;
    }
  | {
      kind: "needs_input";
      trigger: Extract<
        AgentSessionNotificationTrigger,
        | "local_permission_request"
        | "cloud_permission_request"
        | "pi_mcp_permission_request"
      >;
      taskId: string;
      taskRunId?: string;
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
