import type { FocusSagaResult } from "../focus/service";

export const EXTERNAL_APPS_SERVICE = Symbol.for(
  "posthog.core.externalAppsService",
);

export const EXTERNAL_APPS_WORKSPACE_CLIENT = Symbol.for(
  "posthog.core.externalAppsWorkspaceClient",
);

export const EXTERNAL_APPS_FOCUS_COORDINATOR = Symbol.for(
  "posthog.core.externalAppsFocusCoordinator",
);

export interface ExternalAppsDetectedApp {
  id: string;
  name: string;
}

export interface ExternalAppsOpenResult {
  success: boolean;
  error?: string;
}

export interface ExternalAppsWorkspaceClient {
  openInApp(appId: string, targetPath: string): Promise<ExternalAppsOpenResult>;
  setLastUsed(appId: string): Promise<void>;
  getDetectedApps(): Promise<ExternalAppsDetectedApp[]>;
  copyPath(targetPath: string): Promise<void>;
}

export interface ExternalAppsFocusSession {
  worktreePath: string;
}

export interface ExternalAppsFocusParams {
  mainRepoPath: string;
  worktreePath: string;
  branch: string;
}

export interface ExternalAppsFocusCoordinator {
  getSession(): ExternalAppsFocusSession | null;
  enableFocus(params: ExternalAppsFocusParams): Promise<FocusSagaResult>;
}
