import {
  GitServiceEvent,
  type HostGitAgentService,
  type HostGitService,
  type HostGitWorkspaceClient,
} from "@posthog/core/git/host-git";
import {
  GIT_AGENT_SERVICE,
  GIT_SERVICE,
  GIT_WORKSPACE_CLIENT,
} from "@posthog/core/git/identifiers";
import {
  approvePrInput,
  approvePrOutput,
  checkoutBranchInput,
  checkoutBranchOutput,
  cloneRepositoryInput,
  cloneRepositoryOutput,
  commitInput,
  commitOutput,
  createBranchInput,
  createPrInput,
  createPrOutput,
  detectRepoInput,
  detectRepoOutput,
  diffInput,
  diffOutput,
  discardFileChangesInput,
  discardFileChangesOutput,
  generateCommitMessageInput,
  generateCommitMessageOutput,
  generatePrShortSummaryInput,
  generatePrShortSummaryOutput,
  generatePrTitleAndBodyInput,
  generatePrTitleAndBodyOutput,
  getAllBranchesInput,
  getAllBranchesOutput,
  getBranchChangedFilesInput,
  getBranchChangedFilesOutput,
  getChangedFilesHeadInput,
  getChangedFilesHeadOutput,
  getCommitConventionsInput,
  getCommitConventionsOutput,
  getCurrentBranchInput,
  getCurrentBranchOutput,
  getDiffStatsInput,
  getDiffStatsOutput,
  getFileAtHeadInput,
  getFileAtHeadOutput,
  getGitBusyStateInput,
  getGitBusyStateOutput,
  getGithubIssueInput,
  getGithubIssueOutput,
  getGithubPullRequestInput,
  getGithubPullRequestOutput,
  getGitRepoInfoInput,
  getGitRepoInfoOutput,
  getGitSyncStatusOutput,
  getLatestCommitInput,
  getLatestCommitOutput,
  getLocalBranchChangedFilesInput,
  getLocalBranchChangedFilesOutput,
  getPrChangedFilesInput,
  getPrChangedFilesOutput,
  getPrChecksInput,
  getPrChecksOutput,
  getPrCommentsInput,
  getPrCommentsOutput,
  getPrDetailsByUrlInput,
  getPrDetailsByUrlOutput,
  getPrDiffStatsBatchInput,
  getPrDiffStatsBatchOutput,
  getPrInfoByUrlInput,
  getPrInfoByUrlOutput,
  getPrReviewCommentsInput,
  getPrReviewCommentsOutput,
  getPrTemplateInput,
  getPrTemplateOutput,
  getPrUrlForBranchInput,
  getPrUrlForBranchOutput,
  ghAuthTokenOutput,
  ghStatusOutput,
  gitStateSnapshotSchema,
  gitStatusOutput,
  mergePrInput,
  mergePrOutput,
  openPrInput,
  openPrOutput,
  prStatusInput,
  prStatusOutput,
  publishInput,
  publishOutput,
  pullInput,
  pullOutput,
  pushInput,
  pushOutput,
  replyToPrCommentInput,
  replyToPrCommentOutput,
  resolveReviewThreadInput,
  resolveReviewThreadOutput,
  searchGithubRefsInput,
  searchGithubRefsOutput,
  stageFilesInput,
  syncInput,
  syncOutput,
  updatePrByUrlInput,
  updatePrByUrlOutput,
  validateRepoInput,
  validateRepoOutput,
} from "@posthog/core/git/router-schemas";
import type { GitPrService } from "@posthog/core/git-pr/git-pr";
import { GIT_PR_SERVICE } from "@posthog/core/git-pr/identifiers";
import type { ServiceResolver } from "@posthog/host-trpc/context";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { z } from "zod";

const getService = (container: ServiceResolver) =>
  container.get<HostGitService>(GIT_SERVICE);

const getGitPrService = (container: ServiceResolver) =>
  container.get<GitPrService>(GIT_PR_SERVICE);

const getWorkspaceClient = (container: ServiceResolver) =>
  container.get<HostGitWorkspaceClient>(GIT_WORKSPACE_CLIENT);

const getAgentService = (container: ServiceResolver) =>
  container.get<HostGitAgentService>(GIT_AGENT_SERVICE);

const resolveSessionEnv = async (
  container: ServiceResolver,
  taskId: string | undefined,
): Promise<Record<string, string> | undefined> => {
  if (!taskId) return undefined;
  try {
    const env = await getAgentService(container).getSessionEnvForTask(taskId);
    return Object.keys(env).length > 0 ? env : undefined;
  } catch {
    return undefined;
  }
};

export const gitRouter = router({
  detectRepo: publicProcedure
    .input(detectRepoInput)
    .output(detectRepoOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.detectRepo.query({
        directoryPath: input.directoryPath,
      }),
    ),

  validateRepo: publicProcedure
    .input(validateRepoInput)
    .output(validateRepoOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.validateRepo.query({
        directoryPath: input.directoryPath,
      }),
    ),

  cloneRepository: publicProcedure
    .input(cloneRepositoryInput)
    .output(cloneRepositoryOutput)
    .mutation(({ ctx, input }) =>
      getService(ctx.container).cloneRepository(
        input.repoUrl,
        input.targetPath,
        input.cloneId,
      ),
    ),

  onCloneProgress: publicProcedure.subscription(async function* (opts) {
    const service = getService(opts.ctx.container);
    const iterable = service.toIterable(GitServiceEvent.CloneProgress, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),

  getCurrentBranch: publicProcedure
    .input(getCurrentBranchInput)
    .output(getCurrentBranchOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getCurrentBranch.query(
        { directoryPath: input.directoryPath },
        { signal },
      ),
    ),

  getAllBranches: publicProcedure
    .input(getAllBranchesInput)
    .output(getAllBranchesOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getAllBranches.query(
        { directoryPath: input.directoryPath },
        { signal },
      ),
    ),

  getGitBusyState: publicProcedure
    .input(getGitBusyStateInput)
    .output(getGitBusyStateOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getGitBusyState.query(
        { directoryPath: input.directoryPath },
        { signal },
      ),
    ),

  createBranch: publicProcedure
    .input(createBranchInput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.createBranch.mutate({
        directoryPath: input.directoryPath,
        branchName: input.branchName,
      }),
    ),

  checkoutBranch: publicProcedure
    .input(checkoutBranchInput)
    .output(checkoutBranchOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.checkoutBranch.mutate({
        directoryPath: input.directoryPath,
        branchName: input.branchName,
      }),
    ),

  getChangedFilesHead: publicProcedure
    .input(getChangedFilesHeadInput)
    .output(getChangedFilesHeadOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getChangedFilesHead.query(
        { directoryPath: input.directoryPath },
        { signal },
      ),
    ),

  getFileAtHead: publicProcedure
    .input(getFileAtHeadInput)
    .output(getFileAtHeadOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getFileAtHead.query(
        { directoryPath: input.directoryPath, filePath: input.filePath },
        { signal },
      ),
    ),

  getDiffHead: publicProcedure
    .input(diffInput)
    .output(diffOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getDiffHead.query(
        {
          directoryPath: input.directoryPath,
          ignoreWhitespace: input.ignoreWhitespace,
        },
        { signal },
      ),
    ),

  getDiffCached: publicProcedure
    .input(diffInput)
    .output(diffOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getDiffCached.query(
        {
          directoryPath: input.directoryPath,
          ignoreWhitespace: input.ignoreWhitespace,
        },
        { signal },
      ),
    ),

  getDiffUnstaged: publicProcedure
    .input(diffInput)
    .output(diffOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getDiffUnstaged.query(
        {
          directoryPath: input.directoryPath,
          ignoreWhitespace: input.ignoreWhitespace,
        },
        { signal },
      ),
    ),

  getDiffStats: publicProcedure
    .input(getDiffStatsInput)
    .output(getDiffStatsOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getDiffStats.query({
        directoryPath: input.directoryPath,
      }),
    ),

  stageFiles: publicProcedure
    .input(stageFilesInput)
    .output(gitStateSnapshotSchema)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.stageFiles.mutate({
        directoryPath: input.directoryPath,
        paths: input.paths,
      }),
    ),

  unstageFiles: publicProcedure
    .input(stageFilesInput)
    .output(gitStateSnapshotSchema)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.unstageFiles.mutate({
        directoryPath: input.directoryPath,
        paths: input.paths,
      }),
    ),

  discardFileChanges: publicProcedure
    .input(discardFileChangesInput)
    .output(discardFileChangesOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.discardFileChanges.mutate({
        directoryPath: input.directoryPath,
        filePath: input.filePath,
        fileStatus: input.fileStatus,
      }),
    ),

  getGitSyncStatus: publicProcedure
    .input(
      z.object({
        directoryPath: z.string(),
        fetchFromRemote: z.boolean().optional(),
      }),
    )
    .output(getGitSyncStatusOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getGitSyncStatus.query({
        directoryPath: input.directoryPath,
        fetchFromRemote: input.fetchFromRemote,
      }),
    ),

  getLatestCommit: publicProcedure
    .input(getLatestCommitInput)
    .output(getLatestCommitOutput)
    .query(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.getLatestCommit.query(
        { directoryPath: input.directoryPath },
        { signal },
      ),
    ),

  getGitRepoInfo: publicProcedure
    .input(getGitRepoInfoInput)
    .output(getGitRepoInfoOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getGitRepoInfo.query({
        directoryPath: input.directoryPath,
      }),
    ),

  commit: publicProcedure
    .input(commitInput)
    .output(commitOutput)
    .mutation(async ({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.commit.mutate({
        directoryPath: input.directoryPath,
        message: input.message,
        paths: input.paths,
        allowEmpty: input.allowEmpty,
        stagedOnly: input.stagedOnly,
        env: await resolveSessionEnv(ctx.container, input.taskId),
      }),
    ),

  push: publicProcedure
    .input(pushInput)
    .output(pushOutput)
    .mutation(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.push.mutate(
        {
          directoryPath: input.directoryPath,
          remote: input.remote,
          branch: input.branch,
          setUpstream: input.setUpstream,
        },
        { signal },
      ),
    ),

  pull: publicProcedure
    .input(pullInput)
    .output(pullOutput)
    .mutation(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.pull.mutate(
        {
          directoryPath: input.directoryPath,
          remote: input.remote,
          branch: input.branch,
        },
        { signal },
      ),
    ),

  publish: publicProcedure
    .input(publishInput)
    .output(publishOutput)
    .mutation(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.publish.mutate(
        { directoryPath: input.directoryPath, remote: input.remote },
        { signal },
      ),
    ),

  sync: publicProcedure
    .input(syncInput)
    .output(syncOutput)
    .mutation(({ ctx, input, signal }) =>
      getWorkspaceClient(ctx.container).git.sync.mutate(
        { directoryPath: input.directoryPath, remote: input.remote },
        { signal },
      ),
    ),

  getGitStatus: publicProcedure
    .output(gitStatusOutput)
    .query(({ ctx }) =>
      getWorkspaceClient(ctx.container).git.getGitStatus.query(),
    ),

  getGhStatus: publicProcedure
    .output(ghStatusOutput)
    .query(({ ctx }) =>
      getWorkspaceClient(ctx.container).git.getGhStatus.query(),
    ),

  getGhAuthToken: publicProcedure
    .output(ghAuthTokenOutput)
    .query(({ ctx }) =>
      getWorkspaceClient(ctx.container).git.getGhAuthToken.query(),
    ),

  getPrStatus: publicProcedure
    .input(prStatusInput)
    .output(prStatusOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrStatus.query({
        directoryPath: input.directoryPath,
      }),
    ),

  getPrUrlForBranch: publicProcedure
    .input(getPrUrlForBranchInput)
    .output(getPrUrlForBranchOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrUrlForBranch.query({
        directoryPath: input.directoryPath,
        branchName: input.branchName,
      }),
    ),

  createPr: publicProcedure
    .input(createPrInput)
    .output(createPrOutput)
    .mutation(({ ctx, input }) => getService(ctx.container).createPr(input)),

  openPr: publicProcedure
    .input(openPrInput)
    .output(openPrOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.openPr.mutate({
        directoryPath: input.directoryPath,
      }),
    ),

  getPrTemplate: publicProcedure
    .input(getPrTemplateInput)
    .output(getPrTemplateOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrTemplate.query({
        directoryPath: input.directoryPath,
      }),
    ),

  getCommitConventions: publicProcedure
    .input(getCommitConventionsInput)
    .output(getCommitConventionsOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getCommitConventions.query({
        directoryPath: input.directoryPath,
        sampleSize: input.sampleSize,
      }),
    ),

  getPrChangedFiles: publicProcedure
    .input(getPrChangedFilesInput)
    .output(getPrChangedFilesOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrChangedFiles.query({
        prUrl: input.prUrl,
      }),
    ),

  getPrDiffStatsBatch: publicProcedure
    .input(getPrDiffStatsBatchInput)
    .output(getPrDiffStatsBatchOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrDiffStatsBatch.query({
        prUrls: input.prUrls,
      }),
    ),

  getPrDetailsByUrl: publicProcedure
    .input(getPrDetailsByUrlInput)
    .output(getPrDetailsByUrlOutput)
    .query(async ({ ctx, input }) => {
      const result = await getWorkspaceClient(
        ctx.container,
      ).git.getPrDetailsByUrl.query({
        prUrl: input.prUrl,
      });
      return (
        result ?? {
          state: "unknown",
          merged: false,
          draft: false,
          headRefName: null,
          title: null,
        }
      );
    }),

  updatePrByUrl: publicProcedure
    .input(updatePrByUrlInput)
    .output(updatePrByUrlOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.updatePrByUrl.mutate({
        prUrl: input.prUrl,
        action: input.action,
      }),
    ),

  getPrInfoByUrl: publicProcedure
    .input(getPrInfoByUrlInput)
    .output(getPrInfoByUrlOutput.nullable())
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrInfoByUrl.query({
        prUrl: input.prUrl,
      }),
    ),

  getPrChecks: publicProcedure
    .input(getPrChecksInput)
    .output(getPrChecksOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrChecks.query({
        prUrl: input.prUrl,
      }),
    ),

  getPrComments: publicProcedure
    .input(getPrCommentsInput)
    .output(getPrCommentsOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrComments.query({
        prUrl: input.prUrl,
      }),
    ),

  approvePr: publicProcedure
    .input(approvePrInput)
    .output(approvePrOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.approvePr.mutate({
        prUrl: input.prUrl,
      }),
    ),

  mergePr: publicProcedure
    .input(mergePrInput)
    .output(mergePrOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.mergePr.mutate({
        prUrl: input.prUrl,
        method: input.method,
      }),
    ),

  getPrReviewComments: publicProcedure
    .input(getPrReviewCommentsInput)
    .output(getPrReviewCommentsOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getPrReviewComments.query({
        prUrl: input.prUrl,
      }),
    ),

  replyToPrComment: publicProcedure
    .input(replyToPrCommentInput)
    .output(replyToPrCommentOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.replyToPrComment.mutate({
        prUrl: input.prUrl,
        commentId: input.commentId,
        body: input.body,
      }),
    ),

  resolveReviewThread: publicProcedure
    .input(resolveReviewThreadInput)
    .output(resolveReviewThreadOutput)
    .mutation(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.resolveReviewThread.mutate({
        prUrl: input.prUrl,
        threadNodeId: input.threadNodeId,
        resolved: input.resolved,
      }),
    ),

  getBranchChangedFiles: publicProcedure
    .input(getBranchChangedFilesInput)
    .output(getBranchChangedFilesOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getBranchChangedFiles.query({
        repo: input.repo,
        branch: input.branch,
      }),
    ),

  getLocalBranchChangedFiles: publicProcedure
    .input(getLocalBranchChangedFilesInput)
    .output(getLocalBranchChangedFilesOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getLocalBranchChangedFiles.query({
        directoryPath: input.directoryPath,
        branch: input.branch,
      }),
    ),

  generateCommitMessage: publicProcedure
    .input(generateCommitMessageInput)
    .output(generateCommitMessageOutput)
    .mutation(({ ctx, input }) =>
      getGitPrService(ctx.container).generateCommitMessage(
        input.directoryPath,
        input.conversationContext,
      ),
    ),

  generatePrTitleAndBody: publicProcedure
    .input(generatePrTitleAndBodyInput)
    .output(generatePrTitleAndBodyOutput)
    .mutation(({ ctx, input }) =>
      getGitPrService(ctx.container).generatePrTitleAndBody(
        input.directoryPath,
        input.conversationContext,
      ),
    ),

  generatePrShortSummary: publicProcedure
    .input(generatePrShortSummaryInput)
    .output(generatePrShortSummaryOutput)
    .mutation(({ ctx, input }) =>
      getGitPrService(ctx.container).generatePrShortSummary(
        input.conversationContext,
        input.prTitle,
      ),
    ),

  searchGithubRefs: publicProcedure
    .input(searchGithubRefsInput)
    .output(searchGithubRefsOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.searchGithubRefs.query({
        directoryPath: input.directoryPath,
        query: input.query,
        limit: input.limit,
        kinds: input.kinds,
      }),
    ),

  getGithubIssue: publicProcedure
    .input(getGithubIssueInput)
    .output(getGithubIssueOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getGithubIssue.query({
        owner: input.owner,
        repo: input.repo,
        number: input.number,
      }),
    ),

  getGithubPullRequest: publicProcedure
    .input(getGithubPullRequestInput)
    .output(getGithubPullRequestOutput)
    .query(({ ctx, input }) =>
      getWorkspaceClient(ctx.container).git.getGithubPullRequest.query({
        owner: input.owner,
        repo: input.repo,
        number: input.number,
      }),
    ),

  onCreatePrProgress: publicProcedure.subscription(async function* (opts) {
    const service = getService(opts.ctx.container);
    const iterable = service.toIterable(GitServiceEvent.CreatePrProgress, {
      signal: opts.signal,
    });
    for await (const data of iterable) {
      yield data;
    }
  }),
});
