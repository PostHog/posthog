import { saveSettingsBackupInput } from "@posthog/core/settings/schemas";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type ISettingsBackupFiles,
  SETTINGS_BACKUP_FILES,
} from "@posthog/platform/settings-backup-files";

export const settingsBackupRouter = router({
  open: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<ISettingsBackupFiles>(SETTINGS_BACKUP_FILES).open(),
  ),
  save: publicProcedure
    .input(saveSettingsBackupInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<ISettingsBackupFiles>(SETTINGS_BACKUP_FILES)
        .save(input),
    ),
});
