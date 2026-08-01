import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import { injectable } from "inversify";
import {
  getAllWorktreeLocations,
  getAutoSuspendAfterDays,
  getAutoSuspendEnabled,
  getMaxActiveWorktrees,
  getPreventSleepWhileRunning,
  getWorktreeLocation,
  setAutoSuspendAfterDays,
  setAutoSuspendEnabled,
  setMaxActiveWorktrees,
  setPreventSleepWhileRunning,
  setWorktreeLocation,
} from "../services/settingsStore";

@injectable()
export class ElectronWorkspaceSettings implements IWorkspaceSettings {
  getWorktreeLocation(): string {
    return getWorktreeLocation();
  }

  getAllWorktreeLocations(): string[] {
    return getAllWorktreeLocations();
  }

  setWorktreeLocation(location: string): void {
    setWorktreeLocation(location);
  }

  getMaxActiveWorktrees(): number {
    return getMaxActiveWorktrees();
  }

  setMaxActiveWorktrees(value: number): void {
    setMaxActiveWorktrees(value);
  }

  getAutoSuspendEnabled(): boolean {
    return getAutoSuspendEnabled();
  }

  setAutoSuspendEnabled(value: boolean): void {
    setAutoSuspendEnabled(value);
  }

  getAutoSuspendAfterDays(): number {
    return getAutoSuspendAfterDays();
  }

  setAutoSuspendAfterDays(value: number): void {
    setAutoSuspendAfterDays(value);
  }

  getPreventSleepWhileRunning(): boolean {
    return getPreventSleepWhileRunning();
  }

  setPreventSleepWhileRunning(value: boolean): void {
    setPreventSleepWhileRunning(value);
  }
}
