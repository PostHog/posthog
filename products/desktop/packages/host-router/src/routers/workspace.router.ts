import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { WORKSPACE_SERVICE } from "@posthog/workspace-server/services/workspace/identifiers";
import {
  cachedPrUrlInput,
  cachedPrUrlOutput,
  checkWorktreeBranchInput,
  checkWorktreeBranchOutput,
  createWorkspaceInput,
  createWorkspaceOutput,
  deleteWorkspaceInput,
  deleteWorktreeInput,
  ensureScratchDirInput,
  ensureScratchDirOutput,
  getAllTaskTimestampsOutput,
  getAllWorkspacesOutput,
  getLocalTasksInput,
  getLocalTasksOutput,
  getPinnedTaskIdsOutput,
  getTaskTimestampsInput,
  getTaskTimestampsOutput,
  getWorkspaceInfoInput,
  getWorkspaceInfoOutput,
  getWorktreeFileUsageInput,
  getWorktreeFileUsageOutput,
  getWorktreeSizeInput,
  getWorktreeSizeOutput,
  getWorktreeTasksInput,
  getWorktreeTasksOutput,
  linkBranchInput,
  listAdoptableWorktreesInput,
  listAdoptableWorktreesOutput,
  listGitWorktreesInput,
  listGitWorktreesOutput,
  listRepoCheckoutsInput,
  listRepoCheckoutsOutput,
  markActivityInput,
  markViewedInput,
  reconcileCloudWorkspacesInput,
  reconcileCloudWorkspacesOutput,
  setPrimaryPrUrlInput,
  taskPrStatusInput,
  taskPrStatusOutput,
  togglePinInput,
  togglePinOutput,
  unlinkBranchInput,
  verifyWorkspaceInput,
  verifyWorkspaceOutput,
} from "@posthog/workspace-server/services/workspace/schemas";
import {
  type WorkspaceService,
  WorkspaceServiceEvent,
  type WorkspaceServiceEvents,
} from "@posthog/workspace-server/services/workspace/workspace";
import { WORKSPACE_METADATA_SERVICE } from "@posthog/workspace-server/services/workspace-metadata/identifiers";
import type { WorkspaceMetadataService } from "@posthog/workspace-server/services/workspace-metadata/workspace-metadata";
import {
  getWorktreeFileUsage,
  getWorktreeSize,
} from "@posthog/workspace-server/services/worktree-query/worktree-query";
import {
  GIT_PR_STATUS_PROVIDER,
  type IGitPrStatus,
} from "../ports/git-pr-status";

const getService = (container: ServiceResolver) =>
  container.get<WorkspaceService>(WORKSPACE_SERVICE);

const getGitService = (container: ServiceResolver) =>
  container.get<IGitPrStatus>(GIT_PR_STATUS_PROVIDER);

const getMetadata = (container: ServiceResolver) =>
  container.get<WorkspaceMetadataService>(WORKSPACE_METADATA_SERVICE);

function subscribe<K extends keyof WorkspaceServiceEvents>(event: K) {
  return publicProcedure.subscription(async function* (opts) {
    const service = getService(opts.ctx.container);
    const iterable = service.toIterable(event, { signal: opts.signal });
    for await (const data of iterable) {
      yield data;
    }
  });
}

export const workspaceRouter = router({
  create: publicProcedure
    .input(createWorkspaceInput)
    .output(createWorkspaceOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).createWorkspace(input),
    ),

  checkWorktreeBranch: publicProcedure
    .input(checkWorktreeBranchInput)
    .output(checkWorktreeBranchOutput)
    .query(({ ctx, input, signal }) =>
      getService(ctx.container).checkWorktreeBranch(input, signal),
    ),

  reconcileCloudWorkspaces: publicProcedure
    .input(reconcileCloudWorkspacesInput)
    .output(reconcileCloudWorkspacesOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).reconcileCloudWorkspaces(input.taskIds),
    ),

  delete: publicProcedure
    .input(deleteWorkspaceInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).deleteWorkspace(
        input.taskId,
        input.mainRepoPath,
      ),
    ),

  verify: publicProcedure
    .input(verifyWorkspaceInput)
    .output(verifyWorkspaceOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).verifyWorkspaceExists(input.taskId),
    ),

  ensureScratchDir: publicProcedure
    .input(ensureScratchDirInput)
    .output(ensureScratchDirOutput)
    .mutation(async ({ ctx, input }) => ({
      path: await getService(ctx.container).ensureScratchDir(input.taskId),
    })),

  getInfo: publicProcedure
    .input(getWorkspaceInfoInput)
    .output(getWorkspaceInfoOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).getWorkspaceInfo(input.taskId),
    ),

  getAll: publicProcedure
    .output(getAllWorkspacesOutput)
    .query(({ ctx }) => getService(ctx.container).getAllWorkspaces()),

  getLocalTasks: publicProcedure
    .input(getLocalTasksInput)
    .output(getLocalTasksOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).getLocalTasksForFolder(input.mainRepoPath),
    ),

  getWorktreeTasks: publicProcedure
    .input(getWorktreeTasksInput)
    .output(getWorktreeTasksOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).getWorktreeTasks(input.worktreePath),
    ),

  listGitWorktrees: publicProcedure
    .input(listGitWorktreesInput)
    .output(listGitWorktreesOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).listGitWorktrees(input.mainRepoPath),
    ),

  listRepoCheckouts: publicProcedure
    .input(listRepoCheckoutsInput)
    .output(listRepoCheckoutsOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).listRepoCheckouts(input.repoPath),
    ),

  listAdoptableWorktrees: publicProcedure
    .input(listAdoptableWorktreesInput)
    .output(listAdoptableWorktreesOutput)
    .query(({ ctx, input }) =>
      getService(ctx.container).listAdoptableWorktrees(input.mainRepoPath),
    ),

  getWorktreeSize: publicProcedure
    .input(getWorktreeSizeInput)
    .output(getWorktreeSizeOutput)
    .query(({ input }) => getWorktreeSize(input.worktreePath)),

  getWorktreeFileUsage: publicProcedure
    .input(getWorktreeFileUsageInput)
    .output(getWorktreeFileUsageOutput)
    .query(({ input }) => getWorktreeFileUsage(input.mainRepoPath)),

  deleteWorktree: publicProcedure
    .input(deleteWorktreeInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).deleteWorktree(
        input.mainRepoPath,
        input.worktreePath,
      ),
    ),

  togglePin: publicProcedure
    .input(togglePinInput)
    .output(togglePinOutput)
    .mutation(({ ctx, input }) =>
      getMetadata(ctx.container).togglePin(input.taskId),
    ),

  markViewed: publicProcedure
    .input(markViewedInput)
    .mutation(({ ctx, input }) =>
      getMetadata(ctx.container).markViewed(input.taskId),
    ),

  markActivity: publicProcedure
    .input(markActivityInput)
    .mutation(({ ctx, input }) =>
      getMetadata(ctx.container).markActivity(input.taskId),
    ),

  getPinnedTaskIds: publicProcedure
    .output(getPinnedTaskIdsOutput)
    .query(({ ctx }) => getMetadata(ctx.container).getPinnedTaskIds()),

  getTaskTimestamps: publicProcedure
    .input(getTaskTimestampsInput)
    .output(getTaskTimestampsOutput)
    .query(({ ctx, input }) =>
      getMetadata(ctx.container).getTaskTimestamps(input.taskId),
    ),

  getAllTaskTimestamps: publicProcedure
    .output(getAllTaskTimestampsOutput)
    .query(({ ctx }) => getMetadata(ctx.container).getAllTaskTimestamps()),

  linkBranch: publicProcedure
    .input(linkBranchInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).linkBranch(
        input.taskId,
        input.branchName,
        "user",
      ),
    ),

  unlinkBranch: publicProcedure
    .input(unlinkBranchInput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).unlinkBranch(input.taskId, "user"),
    ),

  getTaskPrStatus: publicProcedure
    .input(taskPrStatusInput)
    .output(taskPrStatusOutput)
    .query(({ ctx, input }) =>
      getGitService(ctx.container).getTaskPrStatus(
        input.taskId,
        input.cloudPrUrl,
      ),
    ),

  getCachedPrUrl: publicProcedure
    .input(cachedPrUrlInput)
    .output(cachedPrUrlOutput)
    .query(({ ctx, input }) =>
      getGitService(ctx.container).getCachedPrUrl(input.taskId),
    ),

  setPrimaryPrUrl: publicProcedure
    .input(setPrimaryPrUrlInput)
    .mutation(({ ctx, input }) =>
      getGitService(ctx.container).setPrimaryPrUrl(input.taskId, input.prUrl),
    ),

  onError: subscribe(WorkspaceServiceEvent.Error),
  onWarning: subscribe(WorkspaceServiceEvent.Warning),
  onPromoted: subscribe(WorkspaceServiceEvent.Promoted),
  onBranchChanged: subscribe(WorkspaceServiceEvent.BranchChanged),
  onLinkedBranchChanged: subscribe(WorkspaceServiceEvent.LinkedBranchChanged),
  onTaskPrInfoChanged: subscribe(WorkspaceServiceEvent.TaskPrInfoChanged),
});
