import type {
  CloudPermissionOption,
  CloudTaskPermissionRequestUpdate,
} from "@posthog/shared";

export type TerminalStatus = "completed" | "failed" | "stopped";

export interface CloudArtifactRef {
  runId: string;
  artifactId: string;
}

export interface SessionNotificationAttachment {
  kind: "image" | "document";
  uri: string;
  fileName: string;
  mimeType?: string;
  // Set when the attachment was resolved from a cloud `session/prompt` entry.
  // Its bytes live in S3 as a run artifact; the preview is fetched by presigning
  // rather than read off the local device.
  cloudArtifact?: CloudArtifactRef;
}

export interface SessionNotification {
  update?: {
    sessionUpdate?: string;
    content?: { type: string; text: string };
    // Sidecar carrying user-uploaded attachments on user_message_chunk events.
    // The wire format embeds the bytes themselves in a separate serialized
    // cloud-prompt payload sent to the agent; this field exists only so the
    // local feed can render the attachments alongside the echoed text.
    attachments?: SessionNotificationAttachment[];
    title?: string;
    toolCallId?: string;
    status?: "pending" | "in_progress" | "completed" | "failed" | null;
    rawInput?: Record<string, unknown>;
    rawOutput?: unknown;
    entries?: PlanEntry[];
    _meta?: {
      claudeCode?: {
        toolName?: string;
        parentToolCallId?: string;
      };
    };
  };
}

export interface PlanEntry {
  content: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  priority: string;
}

export interface AcpMessage {
  type: "acp_message";
  direction: "client" | "agent";
  ts: number;
  message: unknown;
}

export interface SessionUpdateEvent {
  type: "session_update";
  ts: number;
  notification: SessionNotification;
}

export type SessionEvent = AcpMessage | SessionUpdateEvent;

export interface CloudPermissionResponseSelection {
  optionId: string;
  displayText: string;
  customInput?: string;
  answers?: Record<string, string>;
}

export interface CloudPendingPermissionRequest {
  requestId: string;
  toolCall: CloudTaskPermissionRequestUpdate["toolCall"];
  options: CloudPermissionOption[];
  response?: CloudPermissionResponseSelection;
}

export interface Integration {
  id: number;
  kind: string;
  display_name?: string;
  config?: {
    account?: {
      login?: string;
    };
  };
}

/**
 * A user-scoped GitHub integration from `/api/users/@me/integrations/`.
 * `id` is the PostHog `UserIntegration` UUID (used as `github_user_integration`
 * on task creation); `installation_id` is the numeric GitHub App installation id
 * (used to fetch repos and as the numeric key in `RepositoryOption`).
 */
export interface UserGithubIntegration {
  id: string;
  kind: string;
  installation_id: string;
  account?: {
    name?: string;
    type?: string;
  };
}

export interface RepositoryOption {
  integrationId: number;
  integrationLabel: string;
  repository: string;
}

export interface RepositorySelection {
  integrationId: number | null;
  repository: string | null;
}

export interface CreateTaskOptions {
  description: string;
  title?: string;
  repository?: string;
  github_integration?: number;
  /** User-scoped GitHub integration UUID (UserIntegration pk) for user-authored
   *  cloud runs. Preferred over `github_integration` for interactive tasks. */
  github_user_integration?: string;
}
