import type {
  CloudPermissionOption,
  CloudTaskPermissionRequestUpdate,
} from "@posthog/shared";

export type TerminalStatus = "completed" | "failed" | "stopped";

export interface SessionNotificationAttachment {
  kind: "image" | "document";
  uri: string;
  fileName: string;
  mimeType?: string;
}

export interface PlanEntry {
  content: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  priority: string;
}

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
