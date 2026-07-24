import { existsSync, renameSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { LEGACY_DATA_DIRS, WORKTREES_DIR } from "@shared/constants";
import Store from "electron-store";
import { getUserDataDir, isDevBuild } from "../utils/env";

interface SettingsSchema {
  worktreeLocation: string;
  preventSleepWhileRunning: boolean;
  autoSuspendEnabled: boolean;
  maxActiveWorktrees: number;
  autoSuspendAfterDays: number;
  discordPresenceEnabled: boolean;
  discordPresenceShowTaskTitle: boolean;
  discordPresenceShowRepoName: boolean;
}

function getDefaultWorktreeLocation(): string {
  const isDev = isDevBuild();
  const dir = isDev ? `${WORKTREES_DIR}-dev` : WORKTREES_DIR;
  return path.join(os.homedir(), dir);
}

function getLegacyWorktreeLocations(): string[] {
  const isDev = isDevBuild();
  const locations: string[] = [];
  for (const dir of LEGACY_DATA_DIRS) {
    if (isDev) {
      locations.push(path.join(os.homedir(), `${dir}-dev`));
    }
    locations.push(path.join(os.homedir(), dir));
  }
  return locations;
}

/**
 * Migrate legacy directories to current if needed (one-time migration)
 */
function migrateWorktreeDirectory(): void {
  const newPath = getDefaultWorktreeLocation();

  // Only migrate if new path doesn't exist yet
  if (existsSync(newPath)) {
    return;
  }

  // Try to migrate from each legacy location (first one found wins)
  for (const legacyPath of getLegacyWorktreeLocations()) {
    if (existsSync(legacyPath)) {
      try {
        renameSync(legacyPath, newPath);
        return;
      } catch {
        // If rename fails (e.g., cross-device), leave as-is
        // User can manually migrate or continue using legacy location
      }
    }
  }
}

// Run migration before store initialization
migrateWorktreeDirectory();

const schema = {
  worktreeLocation: {
    type: "string" as const,
    default: getDefaultWorktreeLocation(),
  },
  preventSleepWhileRunning: {
    type: "boolean" as const,
    default: false,
  },
  autoSuspendEnabled: {
    type: "boolean" as const,
    default: true,
  },
  maxActiveWorktrees: {
    type: "number" as const,
    default: 5,
    minimum: 1,
    maximum: 50,
  },
  autoSuspendAfterDays: {
    type: "number" as const,
    default: 7,
    minimum: 1,
    maximum: 365,
  },
  discordPresenceEnabled: {
    type: "boolean" as const,
    default: false,
  },
  discordPresenceShowTaskTitle: {
    type: "boolean" as const,
    default: false,
  },
  discordPresenceShowRepoName: {
    type: "boolean" as const,
    default: false,
  },
};

export const settingsStore = new Store<SettingsSchema>({
  name: "settings",
  schema,
  cwd: getUserDataDir(),
  defaults: {
    worktreeLocation: getDefaultWorktreeLocation(),
    preventSleepWhileRunning: false,
    autoSuspendEnabled: true,
    maxActiveWorktrees: 5,
    autoSuspendAfterDays: 7,
    discordPresenceEnabled: false,
    discordPresenceShowTaskTitle: false,
    discordPresenceShowRepoName: false,
  },
});

/**
 * Migrate stored worktree setting from legacy to current if it was a legacy default
 */
function migrateWorktreeSetting(): void {
  const stored = settingsStore.get("worktreeLocation");
  const newDefault = getDefaultWorktreeLocation();

  for (const legacyPath of getLegacyWorktreeLocations()) {
    if (stored === legacyPath && existsSync(newDefault)) {
      settingsStore.set("worktreeLocation", newDefault);
      return;
    }
  }
}

// Run setting migration after store initialization
migrateWorktreeSetting();

export function getWorktreeLocation(): string {
  return settingsStore.get("worktreeLocation", getDefaultWorktreeLocation());
}

/**
 * Get all worktree locations to check (current + legacy).
 * Use this when searching for existing worktrees for backwards compatibility.
 */
export function getAllWorktreeLocations(): string[] {
  const primary = getWorktreeLocation();
  const locations = [primary];

  // Add legacy locations if they exist and aren't the primary
  for (const legacyPath of getLegacyWorktreeLocations()) {
    if (legacyPath !== primary && existsSync(legacyPath)) {
      locations.push(legacyPath);
    }
  }

  return locations;
}

export function setWorktreeLocation(location: string): void {
  settingsStore.set("worktreeLocation", location);
}

export function getAutoSuspendEnabled(): boolean {
  return settingsStore.get("autoSuspendEnabled", true);
}

export function setAutoSuspendEnabled(value: boolean): void {
  settingsStore.set("autoSuspendEnabled", value);
}

export function getMaxActiveWorktrees(): number {
  return settingsStore.get("maxActiveWorktrees", 5);
}

export function setMaxActiveWorktrees(value: number): void {
  settingsStore.set("maxActiveWorktrees", value);
}

export function getAutoSuspendAfterDays(): number {
  return settingsStore.get("autoSuspendAfterDays", 7);
}

export function setAutoSuspendAfterDays(value: number): void {
  settingsStore.set("autoSuspendAfterDays", value);
}

export function getPreventSleepWhileRunning(): boolean {
  return settingsStore.get("preventSleepWhileRunning", false);
}

export function setPreventSleepWhileRunning(value: boolean): void {
  settingsStore.set("preventSleepWhileRunning", value);
}
