import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import { injectable } from "inversify";
import {
  getAllWorktreeLocations,
  getAutoSuspendAfterDays,
  getAutoSuspendEnabled,
  getMaxActiveWorktrees,
  getPreventSleepWhileRunning,
  getWorktreeLocation,
  getWorktreeNaming,
  setAutoSuspendAfterDays,
  setAutoSuspendEnabled,
  setMaxActiveWorktrees,
  setPreventSleepWhileRunning,
  setWorktreeLocation,
  setWorktreeNaming,
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

  getWorktreeNamingScheme(): "codename" | "descriptive" {
    return getWorktreeNaming();
  }

  setWorktreeNamingScheme(value: "codename" | "descriptive"): void {
    setWorktreeNaming(value);
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
