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

export type TaskBrowserTabKind = "browser" | "preview";

export interface TaskBrowserRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TaskBrowserImage {
  data: string;
  mimeType: "image/jpeg";
}

export interface ITaskBrowserTabs {
  isWebview(tabId: number): boolean;
  isDestroyed(tabId: number): boolean;
  onConsole(tabId: number, listener: (text: string) => void): void;
  onDestroyed(tabId: number, listener: () => void): void;
  url(tabId: number): string;
  title(tabId: number): string;
  waitForLoad(tabId: number): Promise<void>;
  runScript<T>(tabId: number, code: string): Promise<T>;
  zoom(tabId: number): number;
  capture(
    tabId: number,
    rect: TaskBrowserRect | undefined,
  ): Promise<TaskBrowserImage | null>;
  click(tabId: number, x: number, y: number): void;
  pressKey(tabId: number, key: string): void;
  insertText(tabId: number, text: string, clear: boolean): void;
  goBack(tabId: number): void;
  goForward(tabId: number): void;
  reload(tabId: number): void;
  load(tabId: number, url: string): Promise<void>;
  sendCdp(tabId: number, method: string, params: object): Promise<unknown>;
  clearBrowsingData(): Promise<void>;
}

export const TASK_BROWSER_TABS = Symbol.for("posthog.platform.taskBrowserTabs");

export interface ITaskBrowserSettings {
  sites(): Record<string, TaskBrowserSitePolicy>;
  setSites(sites: Record<string, TaskBrowserSitePolicy>): void;
  fullCdpAccess(): boolean;
  setFullCdpAccess(enabled: boolean): void;
}

export const TASK_BROWSER_SETTINGS = Symbol.for(
  "posthog.platform.taskBrowserSettings",
);

export interface BrowserScriptResult {
  ok: boolean;
  output: string;
}

export interface BrowserScriptRun {
  done: Promise<BrowserScriptResult>;
  stop(): void;
}

export interface IBrowserScriptRunner {
  start(
    code: string,
    call: (method: string, args: unknown[]) => Promise<unknown>,
  ): BrowserScriptRun;
}

export const BROWSER_SCRIPT_RUNNER = Symbol.for(
  "posthog.platform.browserScriptRunner",
);

export interface ITaskPreviewSessions {
  authorize(url: string): Promise<string | null>;
}

export const TASK_PREVIEW_SESSIONS = Symbol.for(
  "posthog.platform.taskPreviewSessions",
);
