export interface Task {
  id: string;
  task_number: number | null;
  slug: string;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
  origin_product: string;
  /** Inbox report UUID when origin_product is "signal_report". */
  signal_report?: string | null;
  repository?: string | null;
  github_integration?: number | null;
  internal?: boolean;
  latest_run?: TaskRun;
}

export interface TaskAutomation {
  id: string;
  name: string;
  prompt: string;
  repository: string;
  github_integration?: number | null;
  cron_expression: string;
  timezone?: string | null;
  template_id?: string | null;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  last_task_id: string | null;
  last_task_run_id: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export type TaskRunStatus =
  | "not_started"
  | "queued"
  | "started"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export const TERMINAL_STATUSES = ["completed", "failed", "cancelled"] as const;

// UI-facing terminal outcome for a run. `cancelled` maps to `stopped` (the user
// deliberately halted it) so the UI can distinguish it from a real failure.
export type TerminalStatus = "completed" | "failed" | "stopped";

export function isTerminalStatus(
  status: TaskRunStatus | string | null | undefined,
): boolean {
  return (
    status !== null &&
    status !== undefined &&
    TERMINAL_STATUSES.includes(status as (typeof TERMINAL_STATUSES)[number])
  );
}

export interface TaskRunArtifact {
  id?: string;
  storage_path?: string;
}

export interface TaskRun {
  id: string;
  task: string;
  team: number;
  branch: string | null;
  stage?: string | null;
  environment?: "local" | "cloud";
  status: TaskRunStatus;
  log_url: string;
  error_message: string | null;
  reasoning_effort?: string | null;
  output: Record<string, unknown> | null;
  state: Record<string, unknown>;
  artifacts?: TaskRunArtifact[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface StoredLogEntry {
  type: string;
  timestamp?: string;
  notification?: {
    id?: number;
    method?: string;
    params?: unknown;
    result?: unknown;
    error?: unknown;
  };
  direction?: "client" | "agent";
}

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

export interface CloudPermissionOption {
  kind: string;
  optionId: string;
  name: string;
  _meta?: Record<string, unknown>;
}

export interface CloudPermissionToolCall {
  toolCallId: string;
  title: string;
  kind: string;
  content?: unknown[];
  rawInput?: Record<string, unknown>;
  _meta?: Record<string, unknown>;
}

export interface CloudPermissionResponseSelection {
  optionId: string;
  displayText: string;
  customInput?: string;
  answers?: Record<string, string>;
}

export interface CloudPendingPermissionRequest {
  requestId: string;
  toolCall: CloudPermissionToolCall;
  options: CloudPermissionOption[];
  response?: CloudPermissionResponseSelection;
}

interface CloudTaskUpdateBase {
  taskId: string;
  runId: string;
}

export interface CloudTaskLogsUpdate extends CloudTaskUpdateBase {
  kind: "logs";
  newEntries: StoredLogEntry[];
  totalEntryCount: number;
}

export interface CloudTaskStatusUpdate extends CloudTaskUpdateBase {
  kind: "status";
  status?: TaskRunStatus;
  stage?: string | null;
  output?: Record<string, unknown> | null;
  errorMessage?: string | null;
  branch?: string | null;
}

export interface CloudTaskSnapshotUpdate extends CloudTaskUpdateBase {
  kind: "snapshot";
  newEntries: StoredLogEntry[];
  totalEntryCount: number;
  status?: TaskRunStatus;
  stage?: string | null;
  output?: Record<string, unknown> | null;
  errorMessage?: string | null;
  branch?: string | null;
}

export interface CloudTaskErrorUpdate extends CloudTaskUpdateBase {
  kind: "error";
  errorTitle: string;
  errorMessage: string;
  retryable: boolean;
}

export interface CloudTaskPermissionRequestUpdate extends CloudTaskUpdateBase {
  kind: "permission_request";
  requestId: string;
  toolCall: CloudPermissionToolCall;
  options: CloudPermissionOption[];
}

export type CloudTaskUpdatePayload =
  | CloudTaskLogsUpdate
  | CloudTaskStatusUpdate
  | CloudTaskSnapshotUpdate
  | CloudTaskErrorUpdate
  | CloudTaskPermissionRequestUpdate;

export interface TaskRunStateEvent {
  type: "task_run_state";
  status?: TaskRunStatus;
  stage?: string | null;
  output?: Record<string, unknown> | null;
  error_message?: string | null;
  branch?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
}

export interface PermissionRequestEventData {
  type: "permission_request";
  requestId: string;
  toolCall: CloudPermissionToolCall;
  options: CloudPermissionOption[];
}

export interface SseErrorEventData {
  error: string;
}

export function isTaskRunStateEvent(data: unknown): data is TaskRunStateEvent {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: string }).type === "task_run_state"
  );
}

export function isPermissionRequestEvent(
  data: unknown,
): data is PermissionRequestEventData {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: string }).type === "permission_request" &&
    typeof (data as { requestId?: string }).requestId === "string"
  );
}

export function isKeepaliveEvent(data: unknown): boolean {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: string }).type === "keepalive"
  );
}

export function isSseErrorEvent(data: unknown): data is SseErrorEventData {
  return (
    typeof data === "object" &&
    data !== null &&
    "error" in data &&
    typeof (data as SseErrorEventData).error === "string"
  );
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

export interface CreateTaskAutomationOptions {
  name: string;
  prompt: string;
  repository: string;
  github_integration?: number | null;
  cron_expression: string;
  timezone: string;
  enabled?: boolean;
  template_id?: string | null;
}

export interface UpdateTaskAutomationOptions {
  name?: string;
  prompt?: string;
  repository?: string;
  github_integration?: number | null;
  cron_expression?: string;
  timezone?: string;
  enabled?: boolean;
  template_id?: string | null;
}
