import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  FS_SERVICE,
  type FsCapability,
} from "@posthog/workspace-server/services/fs/identifiers";
import {
  boundedReadResult,
  listRepoFilesInput,
  listRepoFilesOutput,
  readAbsoluteFileInput,
  readRepoFileBoundedInput,
  readRepoFileInput,
  readRepoFileOutput,
  readRepoFilesBoundedInput,
  readRepoFilesBoundedOutput,
  readRepoFilesInput,
  readRepoFilesOutput,
  writeRepoFileInput,
} from "@posthog/workspace-server/services/fs/schemas";

export const fsRouter = router({
  listRepoFiles: publicProcedure
    .input(listRepoFilesInput)
    .output(listRepoFilesOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .listRepoFiles(input.repoPath, input.query, input.limit),
    ),

  readRepoFile: publicProcedure
    .input(readRepoFileInput)
    .output(readRepoFileOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .readRepoFile(input.repoPath, input.filePath),
    ),

  readRepoFiles: publicProcedure
    .input(readRepoFilesInput)
    .output(readRepoFilesOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .readRepoFiles(input.repoPath, input.filePaths),
    ),

  readRepoFileBounded: publicProcedure
    .input(readRepoFileBoundedInput)
    .output(boundedReadResult)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .readRepoFileBounded(input.repoPath, input.filePath, input.maxLines),
    ),

  readRepoFilesBounded: publicProcedure
    .input(readRepoFilesBoundedInput)
    .output(readRepoFilesBoundedOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .readRepoFilesBounded(input.repoPath, input.filePaths, input.maxLines),
    ),

  readAbsoluteFile: publicProcedure
    .input(readAbsoluteFileInput)
    .output(readRepoFileOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .readAbsoluteFile(input.filePath),
    ),

  readFileAsBase64: publicProcedure
    .input(readAbsoluteFileInput)
    .output(readRepoFileOutput)
    .query(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .readFileAsBase64(input.filePath),
    ),

  writeRepoFile: publicProcedure
    .input(writeRepoFileInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<FsCapability>(FS_SERVICE)
        .writeRepoFile(input.repoPath, input.filePath, input.content),
    ),
});
