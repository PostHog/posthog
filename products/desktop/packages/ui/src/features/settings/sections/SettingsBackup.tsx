import {
  type BackupReview,
  type BackupScope,
  SETTINGS_BACKUP_SERVICE,
  type SettingsBackupService,
  SOUND_SETTINGS,
} from "@posthog/core/settings/settingsBackup";
import { useService } from "@posthog/di/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  SettingsCard,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { useSettingsBackupAvailable } from "@posthog/ui/features/settings/hooks/useSettingsBackupAvailable";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useMutation } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";
import { useState } from "react";

const SCOPE_OPTIONS = [
  { value: "all", label: "Settings and sounds" },
  { value: "sounds", label: "Sounds only" },
];
const WARNING_TEXT = {
  unknown: "Unavailable or removed; will be skipped.",
  changed: "Value is no longer supported; will be skipped.",
  sound: "Invalid or duplicate sound; will be skipped.",
  selection: "The selected sound is missing; your current selection will stay.",
};

const CUSTOM_INSTRUCTIONS_PREVIEW_LENGTH = 400;

type BackupOperation = "export" | "open" | "import";

// A sounds-only import reads no other setting, so the other keys in the file
// do not describe the operation the user chose.
function importedSettingKeys(
  review: BackupReview,
  scope: BackupScope,
): string[] {
  return Object.keys(review.settings).filter(
    (key) => scope === "all" || SOUND_SETTINGS.has(key),
  );
}

function instructionsPreview(text: string): string {
  return text.length > CUSTOM_INSTRUCTIONS_PREVIEW_LENGTH
    ? `${text.slice(0, CUSTOM_INSTRUCTIONS_PREVIEW_LENGTH)}…`
    : text;
}

function settingLabel(key: string): string {
  return key
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .replace(/^./, (letter) => letter.toUpperCase());
}

export interface SettingsBackupViewProps {
  soundCount: number;
  scope: BackupScope;
  onScopeChange: (scope: BackupScope) => void;
  busy: BackupOperation | null;
  review: BackupReview | null;
  error: string | null;
  message: string | null;
  onExport: () => void;
  onOpen: () => void;
  onImport: () => void;
  onCancel: () => void;
}

export function SettingsBackupView({
  soundCount,
  scope,
  onScopeChange,
  busy,
  review,
  error,
  message,
  onExport,
  onOpen,
  onImport,
  onCancel,
}: SettingsBackupViewProps): React.ReactElement {
  const settingKeys = review ? importedSettingKeys(review, scope) : [];
  const hasImport =
    review !== null && (review.sounds.length > 0 || settingKeys.length > 0);
  const customInstructions = settingKeys.includes("customInstructions")
    ? (review?.settings.customInstructions ?? "")
    : null;
  // Sound and selection warnings apply to both scopes, because both scopes
  // import sounds.
  const warnings = (review?.warnings ?? []).filter(
    (warning) =>
      scope === "all" ||
      warning.reason === "sound" ||
      warning.reason === "selection" ||
      SOUND_SETTINGS.has(warning.key),
  );
  return (
    <SettingsSection
      label="Back up settings and sounds"
      description="Move your setup to another machine with a single backup file."
    >
      <SettingsCard>
        <div className="flex flex-col gap-3 px-3.5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[13px]">
              {soundCount} custom {soundCount === 1 ? "sound" : "sounds"} on
              this machine
            </span>
            <SettingsSelect
              ariaLabel="Backup contents"
              value={scope}
              options={SCOPE_OPTIONS}
              onChange={(value) => {
                if (value === "all" || value === "sounds") onScopeChange(value);
              }}
              disabled={busy !== null}
            />
          </div>
          <p className="m-0 text-[12px] text-muted-foreground">
            {scope === "sounds"
              ? "Includes your custom audio, selected completion sound, volume, and playback speed setting."
              : "Includes portable preferences, theme, custom instructions, and all custom audio. Accounts, API keys, workspace paths, and machine-specific settings stay on this machine."}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null || review !== null}
              loading={busy === "export"}
              onClick={onExport}
            >
              <Download />
              Export backup
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy !== null || review !== null}
              loading={busy === "open"}
              onClick={onOpen}
            >
              <Upload />
              Import backup
            </Button>
          </div>
          {error && (
            <p
              role="alert"
              className="m-0 break-words text-[12px] text-destructive"
            >
              {error}
            </p>
          )}
          {message && (
            <output className="m-0 text-[12px] text-muted-foreground">
              {message}
            </output>
          )}
        </div>
        {review && (
          <div className="flex min-w-0 flex-col gap-3 px-3.5 py-3">
            <div>
              <h4 className="m-0 font-semibold text-[13px]">Review import</h4>
              <p className="mt-1 mb-0 break-words text-[12px] text-muted-foreground">
                Exported from PostHog Desktop {review.backup.appVersion} on{" "}
                {new Date(review.backup.exportedAt).toLocaleDateString()}.
              </p>
            </div>
            {review.backup.appVersion !== review.currentVersion && (
              <p className="m-0 rounded border border-(--amber-6) bg-(--amber-2) p-2 text-(--amber-11) text-[12px]">
                This machine runs {review.currentVersion}. Settings may have
                changed between versions. Review the warnings before importing.
              </p>
            )}
            <p className="m-0 text-[12px]">
              {scope === "all"
                ? `${settingKeys.length} supported settings will replace matching preferences. Settings absent from the backup will stay as they are.`
                : "Only sounds and their playback settings will be imported."}{" "}
              Existing custom sounds will be kept. Sounds already imported will
              not be added again.
            </p>
            {settingKeys.length > 0 && (
              <details className="text-[12px]">
                <summary className="cursor-pointer font-medium">
                  Show the {settingKeys.length} settings this import writes
                </summary>
                <ul
                  aria-label="Settings to import"
                  className="mt-2 mb-0 max-h-40 list-disc space-y-1 overflow-y-auto pl-4"
                >
                  {settingKeys.map((key) => (
                    <li key={key} className="break-words">
                      {settingLabel(key)}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {customInstructions !== null && (
              <div className="rounded border border-(--amber-6) bg-(--amber-2) p-2 text-(--amber-11) text-[12px]">
                <p className="m-0 font-medium">
                  This import replaces your custom instructions
                </p>
                <p className="m-0 mt-1">
                  The agent reads them in every task. Read the text below before
                  you import.
                </p>
                <p className="m-0 mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-words">
                  {instructionsPreview(customInstructions)}
                </p>
              </div>
            )}
            {review.sounds.length > 0 && (
              <details className="text-[12px]">
                <summary className="cursor-pointer font-medium">
                  Preview {review.sounds.length} custom{" "}
                  {review.sounds.length === 1 ? "sound" : "sounds"}
                </summary>
                <ul className="m-0 mt-2 flex max-h-56 list-none flex-col gap-3 overflow-y-auto p-0">
                  {review.sounds.map((sound) => (
                    <li
                      key={sound.id}
                      className="flex flex-wrap items-center justify-between gap-2"
                    >
                      <span className="min-w-0 break-words">
                        {sound.name}{" "}
                        <span className="text-muted-foreground">
                          ({(sound.durationMs / 1000).toFixed(1)}s)
                        </span>
                      </span>
                      {/* biome-ignore lint/a11y/useMediaCaption: notification sound previews contain no supplied captions. */}
                      <audio
                        controls
                        preload="none"
                        src={sound.dataUrl}
                        aria-label={`Preview ${sound.name}`}
                        className="h-8 w-56 max-w-full"
                      />
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {warnings.length > 0 && (
              <details open className="text-[12px]">
                <summary className="cursor-pointer font-medium">
                  {warnings.length} compatibility{" "}
                  {warnings.length === 1 ? "warning" : "warnings"}
                </summary>
                <ul
                  aria-label="Compatibility warnings"
                  className="mt-2 mb-0 max-h-40 list-disc space-y-1 overflow-y-auto pl-4"
                >
                  {warnings.map((warning, index) => (
                    <li key={`${warning.key}-${index}`} className="break-words">
                      <span className="font-medium">
                        {settingLabel(warning.key)}
                      </span>
                      : {WARNING_TEXT[warning.reason]}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={busy !== null}
                onClick={onCancel}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={busy !== null || !hasImport}
                loading={busy === "import"}
                onClick={onImport}
              >
                {scope === "sounds"
                  ? "Import sounds"
                  : "Import settings and sounds"}
              </Button>
            </div>
          </div>
        )}
      </SettingsCard>
    </SettingsSection>
  );
}

function SettingsBackupConnected(): React.ReactElement {
  const service = useService<SettingsBackupService>(SETTINGS_BACKUP_SERVICE);
  const soundCount = useSettingsStore((state) => state.customSounds.length);
  const [scope, setScope] = useState<BackupScope>("all");
  const [review, setReview] = useState<BackupReview | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const mutation = useMutation({
    onMutate: () => setMessage(null),
    mutationFn: async (operation: BackupOperation): Promise<void> => {
      switch (operation) {
        case "export":
          // A closed save dialog is neither a success nor a failure, so it
          // reports nothing.
          if (await service.exportBackup(scope)) {
            track(ANALYTICS_EVENTS.SETTINGS_BACKUP_EXPORTED, {
              scope,
              sound_count: soundCount,
            });
            setMessage(
              "Backup saved. Copy this file to your other machine, then import it in Advanced settings.",
            );
          }
          break;
        case "open":
          setReview(await service.openBackup());
          break;
        case "import": {
          if (!review) throw new Error("Choose a backup first.");
          const added = await service.importBackup(review, scope);
          track(ANALYTICS_EVENTS.SETTINGS_BACKUP_IMPORTED, {
            scope,
            setting_count: importedSettingKeys(review, scope).length,
            sound_count: review.sounds.length,
            added_sound_count: added,
            warning_count: review.warnings.length,
            backup_app_version: review.backup.appVersion,
            version_matches: review.backup.appVersion === review.currentVersion,
          });
          setReview(null);
          setMessage(
            `Backup imported. Added ${added} custom ${added === 1 ? "sound" : "sounds"}. Your settings are ready to use.`,
          );
          break;
        }
      }
    },
    onError: (error: Error, operation) => {
      if (operation === "export")
        track(ANALYTICS_EVENTS.SETTINGS_BACKUP_EXPORT_FAILED, {
          scope,
          sound_count: soundCount,
          error: error.message,
        });
      else
        track(ANALYTICS_EVENTS.SETTINGS_BACKUP_IMPORT_FAILED, {
          scope,
          stage: operation === "open" ? "open" : "apply",
          error: error.message,
        });
    },
  });
  return (
    <SettingsBackupView
      soundCount={soundCount}
      scope={scope}
      onScopeChange={setScope}
      review={review}
      error={mutation.error?.message ?? null}
      message={message}
      busy={mutation.isPending ? mutation.variables : null}
      onExport={() => mutation.mutate("export")}
      onOpen={() => mutation.mutate("open")}
      onImport={() => mutation.mutate("import")}
      onCancel={() => {
        setReview(null);
        mutation.reset();
      }}
    />
  );
}

export function SettingsBackup(): React.ReactElement | null {
  const available = useSettingsBackupAvailable();
  return available ? <SettingsBackupConnected /> : null;
}
