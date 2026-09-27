export interface TaskBrowserOpenRequest {
  taskId: string;
  browserId: string;
  url: string;
}

export interface TaskBrowserCloseRequest {
  taskId: string;
  browserId: string;
}

export type TaskBrowserPermissionKind =
  | "site"
  | "sensitive-action"
  | "sign-in"
  | "full-cdp";

export type TaskBrowserPermissionDecision =
  | "allow-once"
  | "allow-task"
  | "allow-always"
  | "deny"
  | "block";

export interface TaskBrowserPermissionRequest {
  requestId: string;
  taskId: string;
  kind: TaskBrowserPermissionKind;
  origin: string;
  detail: string;
}

export type TaskBrowserSitePolicy = "allow" | "block";

export interface TaskBrowserSettings {
  sites: Record<string, TaskBrowserSitePolicy>;
  fullCdpAccess: boolean;
}

export interface ITaskBrowserHost {
  onOpenRequest(
    listener: (request: TaskBrowserOpenRequest) => void,
  ): () => void;
  onCloseRequest(
    listener: (request: TaskBrowserCloseRequest) => void,
  ): () => void;
  onPermissionRequest(
    listener: (request: TaskBrowserPermissionRequest) => void,
  ): () => void;
  onPermissionSettled(listener: (requestId: string) => void): () => void;
  respondToPermission(
    requestId: string,
    decision: TaskBrowserPermissionDecision,
  ): Promise<void>;
  getSettings(): Promise<TaskBrowserSettings>;
  setSitePolicy(
    origin: string,
    policy: TaskBrowserSitePolicy | null,
  ): Promise<void>;
  setFullCdpAccess(enabled: boolean): Promise<void>;
  clearBrowsingData(): Promise<void>;
}

export const TASK_BROWSER_HOST = Symbol.for("posthog.platform.taskBrowserHost");
