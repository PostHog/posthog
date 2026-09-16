export interface ISettingsBackupFiles {
  getAppVersion(): Promise<string>;
  open(): Promise<string | null>;
  save(input: { contents: string; defaultName: string }): Promise<boolean>;
}

export const SETTINGS_BACKUP_FILES = Symbol.for(
  "posthog.platform.settingsBackupFiles",
);
