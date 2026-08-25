import {
  checkoutInput,
  FOCUS_SERVICE,
  FocusServiceEvent,
  type FocusServiceEvents,
  findWorktreeInput,
  focusResultSchema,
  focusSessionSchema,
  type IFocusService,
  mainRepoPathInput,
  reattachInput,
  repoPathInput,
  stashInput,
  stashResultSchema,
  syncInput,
  worktreeInput,
} from "@posthog/core/focus/identifiers";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

function subscribe<K extends keyof FocusServiceEvents>(event: K) {
  return publicProcedure.subscription(async function* (opts) {
    const service = opts.ctx.container.get<IFocusService>(FOCUS_SERVICE);
    const iterable = service.toIterable(event, { signal: opts.signal });
    for await (const data of iterable) {
      yield data;
    }
  });
}

export const focusRouter = router({
  getSession: publicProcedure
    .input(mainRepoPathInput)
    .output(focusSessionSchema.nullable())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .getSession(input.mainRepoPath),
    ),

  saveSession: publicProcedure
    .input(focusSessionSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IFocusService>(FOCUS_SERVICE).saveSession(input),
    ),

  deleteSession: publicProcedure
    .input(mainRepoPathInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .deleteSession(input.mainRepoPath),
    ),

  isFocusActive: publicProcedure
    .input(mainRepoPathInput)
    .output(z.boolean())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .isFocusActive(input.mainRepoPath),
    ),

  validateFocusOperation: publicProcedure
    .input(
      z.object({
        mainRepoPath: z.string(),
        currentBranch: z.string().nullable(),
        targetBranch: z.string(),
      }),
    )
    .output(z.string().nullable())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .validateFocusOperation(input.currentBranch, input.targetBranch),
    ),

  isDirty: publicProcedure
    .input(repoPathInput)
    .output(z.boolean())
    .query(({ ctx, input }) =>
      ctx.container.get<IFocusService>(FOCUS_SERVICE).isDirty(input.repoPath),
    ),

  getCommitSha: publicProcedure
    .input(repoPathInput)
    .output(z.string())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .getCommitSha(input.repoPath),
    ),

  findWorktreeByBranch: publicProcedure
    .input(findWorktreeInput)
    .output(z.string().nullable())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .findWorktreeByBranch(input.mainRepoPath, input.branch),
    ),

  toRelativeWorktreePath: publicProcedure
    .input(z.object({ absolutePath: z.string(), mainRepoPath: z.string() }))
    .output(z.string())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .toRelativeWorktreePath(input.absolutePath, input.mainRepoPath),
    ),

  toAbsoluteWorktreePath: publicProcedure
    .input(z.object({ relativePath: z.string() }))
    .output(z.string())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .toAbsoluteWorktreePath(input.relativePath),
    ),

  worktreeExistsAtPath: publicProcedure
    .input(z.object({ relativePath: z.string() }))
    .output(z.boolean())
    .query(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .worktreeExistsAtPath(input.relativePath),
    ),

  stash: publicProcedure
    .input(stashInput)
    .output(stashResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .stash(input.repoPath, input.message),
    ),

  stashPop: publicProcedure
    .input(repoPathInput)
    .output(focusResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container.get<IFocusService>(FOCUS_SERVICE).stashPop(input.repoPath),
    ),

  stashApply: publicProcedure
    .input(z.object({ repoPath: z.string(), stashRef: z.string() }))
    .output(focusResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .stashApply(input.repoPath, input.stashRef),
    ),

  checkout: publicProcedure
    .input(checkoutInput)
    .output(focusResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .checkout(input.repoPath, input.branch),
    ),

  detachWorktree: publicProcedure
    .input(worktreeInput)
    .output(focusResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .detachWorktree(input.worktreePath),
    ),

  reattachWorktree: publicProcedure
    .input(reattachInput)
    .output(focusResultSchema)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .reattachWorktree(input.worktreePath, input.branch),
    ),

  cleanWorkingTree: publicProcedure
    .input(repoPathInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .cleanWorkingTree(input.repoPath),
    ),

  startSync: publicProcedure
    .input(syncInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .startSync(input.mainRepoPath, input.worktreePath),
    ),

  stopSync: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<IFocusService>(FOCUS_SERVICE).stopSync(),
  ),

  startWatchingMainRepo: publicProcedure
    .input(mainRepoPathInput)
    .mutation(({ ctx, input }) =>
      ctx.container
        .get<IFocusService>(FOCUS_SERVICE)
        .startWatchingMainRepo(input.mainRepoPath),
    ),

  stopWatchingMainRepo: publicProcedure.mutation(({ ctx }) =>
    ctx.container.get<IFocusService>(FOCUS_SERVICE).stopWatchingMainRepo(),
  ),

  onBranchRenamed: subscribe(FocusServiceEvent.BranchRenamed),
  onForeignBranchCheckout: subscribe(FocusServiceEvent.ForeignBranchCheckout),
});
