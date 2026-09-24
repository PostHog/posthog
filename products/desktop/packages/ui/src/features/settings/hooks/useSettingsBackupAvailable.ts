import { useServiceOptional } from "@posthog/di/react";
import { SETTINGS_BACKUP_FILES } from "@posthog/platform/settings-backup-files";
import { SETTINGS_BACKUP_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";

export function useSettingsBackupAvailable(): boolean {
  const files = useServiceOptional(SETTINGS_BACKUP_FILES);
  const enabled = useFeatureFlag(SETTINGS_BACKUP_FLAG);
  return files !== null && enabled;
}
