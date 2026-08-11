import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import { OS_SERVICE } from "@posthog/workspace-server/services/os/identifiers";
import type { OsService } from "@posthog/workspace-server/services/os/os";
import {
  checkWriteAccessInput,
  claudePermissionsOutput,
  downscaleImageFileInput,
  openExternalInput,
  readFileAsDataUrlInput,
  saveClipboardFileInput,
  saveClipboardImageInput,
  saveClipboardTextInput,
  searchDirectoriesInput,
  selectAttachmentsInput,
  selectAttachmentsOutput,
  selectFilesOutput,
  showMessageBoxInput,
  userAgentInstructionsOutput,
} from "@posthog/workspace-server/services/os/schemas";

export const osRouter = router({
  getClaudePermissions: publicProcedure
    .output(claudePermissionsOutput)
    .query(({ ctx }) =>
      ctx.container.get<OsService>(OS_SERVICE).getClaudePermissions(),
    ),

  getUserAgentInstructions: publicProcedure
    .output(userAgentInstructionsOutput)
    .query(({ ctx }) =>
      ctx.container.get<OsService>(OS_SERVICE).getUserAgentInstructions(),
    ),

  selectDirectory: publicProcedure.query(({ ctx }) =>
    ctx.container.get<OsService>(OS_SERVICE).selectDirectory(),
  ),

  selectFiles: publicProcedure
    .output(selectFilesOutput)
    .query(({ ctx }) => ctx.container.get<OsService>(OS_SERVICE).selectFiles()),

  selectAttachments: publicProcedure
    .input(selectAttachmentsInput)
    .output(selectAttachmentsOutput)
    .query(({ ctx, input }) =>
      ctx.container.get<OsService>(OS_SERVICE).selectAttachments(input.mode),
    ),

  checkWriteAccess: publicProcedure
    .input(checkWriteAccessInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<OsService>(OS_SERVICE)
        .checkWriteAccess(input.directoryPath),
    ),

  showMessageBox: publicProcedure
    .input(showMessageBoxInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<OsService>(OS_SERVICE).showMessageBox(input.options),
    ),

  openExternal: publicProcedure
    .input(openExternalInput)
    .mutation(({ ctx, input }) =>
      ctx.container.get<OsService>(OS_SERVICE).openExternal(input.url),
    ),

  showLogFolder: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<OsService>(OS_SERVICE).showLogFolder(),
  ),

  searchDirectories: publicProcedure
    .input(searchDirectoriesInput)
    .query(({ ctx, input }) =>
      ctx.container.get<OsService>(OS_SERVICE).searchDirectories(input.query),
    ),

  getAppVersion: publicProcedure.query(({ ctx }) =>
    ctx.container.get<OsService>(OS_SERVICE).getAppVersion(),
  ),

  getWorktreeLocation: publicProcedure.query(({ ctx }) =>
    ctx.container.get<OsService>(OS_SERVICE).getWorktreeLocation(),
  ),

  readFileAsDataUrl: publicProcedure
    .input(readFileAsDataUrlInput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<OsService>(OS_SERVICE)
        .readFileAsDataUrl(input.filePath, input.maxSizeBytes),
    ),

  saveClipboardText: publicProcedure
    .input(saveClipboardTextInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<OsService>(OS_SERVICE)
        .saveClipboardText(input.text, input.originalName),
    ),

  saveClipboardImage: publicProcedure
    .input(saveClipboardImageInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<OsService>(OS_SERVICE)
        .saveClipboardImage(
          input.base64Data,
          input.mimeType,
          input.originalName,
        ),
    ),

  downscaleImageFile: publicProcedure
    .input(downscaleImageFileInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<OsService>(OS_SERVICE)
        .downscaleImageFile(input.filePath),
    ),

  saveClipboardFile: publicProcedure
    .input(saveClipboardFileInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<OsService>(OS_SERVICE)
        .saveClipboardFile(input.base64Data, input.originalName),
    ),

  zoomIn: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<IMainWindow>(MAIN_WINDOW_SERVICE).zoomIn(),
  ),

  zoomOut: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<IMainWindow>(MAIN_WINDOW_SERVICE).zoomOut(),
  ),

  resetZoom: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<IMainWindow>(MAIN_WINDOW_SERVICE).resetZoom(),
  ),
});
