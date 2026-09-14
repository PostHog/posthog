import {
  type ISettingsBackupFiles,
  SETTINGS_BACKUP_FILES,
} from "@posthog/platform/settings-backup-files";
import { inject, injectable } from "inversify";
import {
  type CustomSound,
  customSoundSchema,
  MAX_SETTINGS_BACKUP_BYTES,
  MAX_SETTINGS_BACKUP_ENTRIES,
  type PortableSettings,
  portableSettingsSchema,
  SETTINGS_BACKUP_FORMAT_VERSION,
  type SettingsBackup,
  settingsBackupSchema,
} from "./schemas";

export type BackupScope = "all" | "sounds";
export interface SettingsBackupSnapshot {
  settings: PortableSettings;
  sounds: CustomSound[];
}
export interface SettingsBackupState {
  read(): SettingsBackupSnapshot;
  apply(snapshot: SettingsBackupSnapshot): Promise<void>;
}
export const SETTINGS_BACKUP_STATE = Symbol.for("posthog.settings.backupState");
export const SETTINGS_BACKUP_SERVICE = Symbol.for(
  "posthog.settings.backupService",
);

export interface BackupWarning {
  key: string;
  reason: "unknown" | "changed" | "sound" | "selection";
}
export interface BackupReview {
  backup: SettingsBackup;
  settings: PortableSettings;
  sounds: CustomSound[];
  warnings: BackupWarning[];
  currentVersion: string;
}

export const SOUND_SETTINGS: ReadonlySet<string> = new Set([
  "completionSound",
  "completionVolume",
  "scaleSoundWithTaskLength",
]);

export interface SettingsBackupSoundMerge {
  sounds: CustomSound[];
  remappedIds: Map<string, string>;
}

export function mergeSettingsBackupSounds(
  currentSounds: CustomSound[],
  importedSounds: CustomSound[],
): SettingsBackupSoundMerge {
  const sounds = [...currentSounds];
  const remappedIds = new Map<string, string>();
  for (const sound of importedSounds) {
    const existing = sounds.find(
      (candidate) =>
        candidate.dataUrl === sound.dataUrl && candidate.name === sound.name,
    );
    if (existing) {
      remappedIds.set(sound.id, existing.id);
      continue;
    }
    let id = sound.id;
    let suffix = 1;
    while (sounds.some((candidate) => candidate.id === id))
      id = `${sound.id.slice(0, 220)}-import-${suffix++}`;
    sounds.push({ ...sound, id });
    remappedIds.set(sound.id, id);
  }
  return { sounds, remappedIds };
}

@injectable()
export class SettingsBackupService {
  private busy = false;

  constructor(
    @inject(SETTINGS_BACKUP_STATE) private readonly state: SettingsBackupState,
    @inject(SETTINGS_BACKUP_FILES) private readonly files: ISettingsBackupFiles,
  ) {}

  private async exclusively<T>(action: () => Promise<T>): Promise<T> {
    if (this.busy)
      throw new Error(
        "A backup operation is already running. Wait for it to finish.",
      );
    this.busy = true;
    try {
      return await action();
    } finally {
      this.busy = false;
    }
  }

  async exportBackup(scope: BackupScope): Promise<boolean> {
    return this.exclusively(async () => {
      const snapshot = this.state.read();
      if (snapshot.sounds.length > MAX_SETTINGS_BACKUP_ENTRIES)
        throw new Error(
          "This backup has more than 1,000 sounds. Remove unused clips and try again.",
        );
      const settings = portableSettingsSchema.safeParse(
        Object.fromEntries(
          Object.entries(snapshot.settings).filter(
            ([key]) => scope === "all" || SOUND_SETTINGS.has(key),
          ),
        ),
      );
      if (!settings.success)
        throw new Error(
          "Some saved settings are no longer supported. Export sounds only, or reset the affected preferences before trying again.",
        );
      const sounds = snapshot.sounds.map((sound) => {
        const result = customSoundSchema.safeParse(sound);
        if (!result.success)
          throw new Error(
            `Could not back up sound “${sound.name}”. Reimport that clip in Notifications settings and try again.`,
          );
        return result.data;
      });
      const backup: SettingsBackup = {
        format: "posthog-desktop-settings",
        formatVersion: SETTINGS_BACKUP_FORMAT_VERSION,
        appVersion: await this.files.getAppVersion(),
        exportedAt: new Date().toISOString(),
        settings: settings.data,
        sounds,
      };
      const contents = JSON.stringify(backup, null, 2);
      if (
        new TextEncoder().encode(contents).length > MAX_SETTINGS_BACKUP_BYTES
      ) {
        throw new Error(
          "This backup exceeds 64 MB. Remove unused clips and try again.",
        );
      }
      return this.files.save({
        contents,
        defaultName: `posthog-${scope === "sounds" ? "sounds" : "settings"}-${backup.exportedAt.slice(0, 10)}.json`,
      });
    });
  }

  inspect(contents: string, currentVersion: string): BackupReview {
    if (new TextEncoder().encode(contents).length > MAX_SETTINGS_BACKUP_BYTES)
      throw new Error(
        "This file exceeds 64 MB. Choose a smaller PostHog backup.",
      );
    let raw: unknown;
    try {
      raw = JSON.parse(contents);
    } catch {
      throw new Error(
        "This file is not valid JSON. Choose a PostHog settings backup.",
      );
    }
    const result = settingsBackupSchema.safeParse(raw);
    if (!result.success)
      throw new Error(
        "This is not a valid PostHog settings backup. Choose a file exported from Advanced settings.",
      );
    const backup = result.data;
    if (backup.formatVersion !== SETTINGS_BACKUP_FORMAT_VERSION)
      throw new Error(
        "This backup uses a newer file format. Update PostHog Desktop before importing it.",
      );
    const warnings: BackupWarning[] = [];
    const settings: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(backup.settings)) {
      if (!Object.hasOwn(portableSettingsSchema.shape, key)) {
        warnings.push({ key, reason: "unknown" });
        continue;
      }
      const schema =
        portableSettingsSchema.shape[key as keyof PortableSettings];
      const parsed = schema.safeParse(value);
      if (parsed.success) settings[key] = parsed.data;
      else warnings.push({ key, reason: "changed" });
    }
    const sounds: CustomSound[] = [];
    const ids = new Set<string>();
    for (const [index, value] of backup.sounds.entries()) {
      const parsed = customSoundSchema.safeParse(value);
      if (!parsed.success || ids.has(parsed.data.id)) {
        warnings.push({ key: `Sound ${index + 1}`, reason: "sound" });
        continue;
      }
      ids.add(parsed.data.id);
      sounds.push(parsed.data);
    }
    const selected = settings.completionSound;
    if (
      typeof selected === "string" &&
      ((selected.startsWith("custom:") && !ids.has(selected.slice(7))) ||
        (selected === "random-custom" && sounds.length === 0))
    ) {
      delete settings.completionSound;
      warnings.push({ key: "Completion sound", reason: "selection" });
    }
    return {
      backup,
      settings: portableSettingsSchema.parse(settings),
      sounds,
      warnings,
      currentVersion,
    };
  }

  async openBackup(): Promise<BackupReview | null> {
    return this.exclusively(async () => {
      const contents = await this.files.open();
      return contents === null
        ? null
        : this.inspect(contents, await this.files.getAppVersion());
    });
  }

  async importBackup(
    review: BackupReview,
    scope: BackupScope,
  ): Promise<number> {
    return this.exclusively(async () => {
      // Revalidate at the write boundary; only the reviewed file supplies values.
      const validated = this.inspect(
        JSON.stringify(review.backup),
        review.currentVersion,
      );
      const current = this.state.read();
      const { sounds, remappedIds } = mergeSettingsBackupSounds(
        current.sounds,
        validated.sounds,
      );
      const settings = portableSettingsSchema.parse(
        Object.fromEntries(
          Object.entries(validated.settings).filter(
            ([key]) => scope === "all" || SOUND_SETTINGS.has(key),
          ),
        ),
      );
      if (settings.completionSound?.startsWith("custom:")) {
        settings.completionSound = `custom:${remappedIds.get(settings.completionSound.slice(7))}`;
      }
      await this.state.apply({ settings, sounds });
      return sounds.length - current.sounds.length;
    });
  }
}
