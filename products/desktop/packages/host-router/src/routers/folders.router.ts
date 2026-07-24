import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import type { FoldersService } from "@posthog/workspace-server/services/folders/folders";
import { FOLDERS_SERVICE } from "@posthog/workspace-server/services/folders/identifiers";
import {
  addFolderInput,
  addFolderOutput,
  getFoldersOutput,
  getRepositoryByRemoteUrlInput,
  removeFolderInput,
  repositoryLookupResult,
  updateFolderAccessedInput,
} from "@posthog/workspace-server/services/folders/schemas";

export const foldersRouter = router({
  getFolders: publicProcedure.output(getFoldersOutput).query(({ ctx }) => {
    return ctx.container.get<FoldersService>(FOLDERS_SERVICE).getFolders();
  }),

  addFolder: publicProcedure
    .input(addFolderInput)
    .output(addFolderOutput)
    .mutation(({ ctx, input }) => {
      return ctx.container
        .get<FoldersService>(FOLDERS_SERVICE)
        .addFolder(input.folderPath, { remoteUrl: input.remoteUrl });
    }),

  removeFolder: publicProcedure
    .input(removeFolderInput)
    .mutation(({ ctx, input }) => {
      return ctx.container
        .get<FoldersService>(FOLDERS_SERVICE)
        .removeFolder(input.folderId);
    }),

  updateFolderAccessed: publicProcedure
    .input(updateFolderAccessedInput)
    .mutation(({ ctx, input }) => {
      return ctx.container
        .get<FoldersService>(FOLDERS_SERVICE)
        .updateFolderAccessed(input.folderId);
    }),

  clearAllData: publicProcedure.mutation(({ ctx }) => {
    return ctx.container.get<FoldersService>(FOLDERS_SERVICE).clearAllData();
  }),

  getRepositoryByRemoteUrl: publicProcedure
    .input(getRepositoryByRemoteUrlInput)
    .output(repositoryLookupResult)
    .query(({ ctx, input }) => {
      return ctx.container
        .get<FoldersService>(FOLDERS_SERVICE)
        .getRepositoryByRemoteUrl(input.remoteUrl);
    }),

  getMostRecentlyAccessedRepository: publicProcedure
    .output(repositoryLookupResult)
    .query(({ ctx }) => {
      return ctx.container
        .get<FoldersService>(FOLDERS_SERVICE)
        .getMostRecentlyAccessedRepository();
    }),
});
