export interface IWorkspaceSettings {
  getWorktreeLocation(): string;
  getAllWorktreeLocations(): string[];
  setWorktreeLocation(location: string): void;
  getMaxActiveWorktrees(): number;
  setMaxActiveWorktrees(value: number): void;
  getAutoSuspendEnabled(): boolean;
  setAutoSuspendEnabled(value: boolean): void;
  getAutoSuspendAfterDays(): number;
  setAutoSuspendAfterDays(value: number): void;
  getPreventSleepWhileRunning(): boolean;
  setPreventSleepWhileRunning(value: boolean): void;
}

export const WORKSPACE_SETTINGS_SERVICE = Symbol.for(
  "posthog.platform.workspaceSettings",
);
