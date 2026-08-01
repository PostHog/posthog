import {
  type GitHubIssue,
  type GithubIssueState,
  type GithubPullRequest,
  type GithubRef,
  type GithubRefKind,
  type GithubRefState,
  githubIssueSchema,
  githubIssueStateSchema,
  githubRefKindSchema,
  githubRefSchema,
  githubRefStateSchema,
  type PrActionType,
  type PrReviewComment,
  type PrReviewThread,
  prActionTypeSchema,
  prReviewCommentSchema,
  prReviewCommentUserSchema,
  prReviewThreadSchema,
} from "@posthog/shared";
import { z } from "zod";

export const directoryPathInput = z.object({
  directoryPath: z.string(),
});

export const gitFileStatusSchema = z.enum([
  "modified",
  "added",
  "deleted",
  "renamed",
  "untracked",
]);

export type GitFileStatus = z.infer<typeof gitFileStatusSchema>;

export const changedFileSchema = z.object({
  path: z.string(),
  status: gitFileStatusSchema,
  originalPath: z.string().optional(),
  linesAdded: z.number().optional(),
  linesRemoved: z.number().optional(),
  staged: z.boolean().optional(),
  patch: z.string().optional(),
  sha: z.string().optional(),
});

export type ChangedFile = z.infer<typeof changedFileSchema>;

export const diffStatsSchema = z.object({
  filesChanged: z.number(),
  linesAdded: z.number(),
  linesRemoved: z.number(),
});

export type DiffStats = z.infer<typeof diffStatsSchema>;

export const gitSyncStatusSchema = z.object({
  aheadOfRemote: z.number(),
  behind: z.number(),
  aheadOfDefault: z.number(),
  hasRemote: z.boolean(),
  currentBranch: z.string().nullable(),
  isFeatureBranch: z.boolean(),
});

export type GitSyncStatus = z.infer<typeof gitSyncStatusSchema>;

export const gitCommitInfoSchema = z.object({
  sha: z.string(),
  shortSha: z.string(),
  message: z.string(),
  author: z.string(),
  date: z.string(),
});

export type GitCommitInfo = z.infer<typeof gitCommitInfoSchema>;

export const gitRepoInfoSchema = z.object({
  organization: z.string(),
  repository: z.string(),
  currentBranch: z.string().nullable(),
  defaultBranch: z.string(),
  compareUrl: z.string().nullable(),
});

export type GitRepoInfo = z.infer<typeof gitRepoInfoSchema>;

export const detectRepoInput = z.object({
  directoryPath: z.string(),
});

export const detectRepoOutput = z
  .object({
    organization: z.string(),
    repository: z.string(),
    remote: z.string().optional(),
    branch: z.string().optional(),
  })
  .nullable();

export type DetectRepoInput = z.infer<typeof detectRepoInput>;
export type DetectRepoResult = z.infer<typeof detectRepoOutput>;

export const validateRepoInput = z.object({
  directoryPath: z.string(),
});

export const validateRepoOutput = z.boolean();

export const cloneRepositoryInput = z.object({
  repoUrl: z.string(),
  targetPath: z.string(),
  cloneId: z.string(),
});

export const cloneRepositoryOutput = z.object({
  cloneId: z.string(),
});

export const cloneProgressStatus = z.enum(["cloning", "complete", "error"]);

export const cloneProgressPayload = z.object({
  cloneId: z.string(),
  status: cloneProgressStatus,
  message: z.string(),
});

export type CloneProgressPayload = z.infer<typeof cloneProgressPayload>;

export const getChangedFilesHeadInput = directoryPathInput;
export const getChangedFilesHeadOutput = z.array(changedFileSchema);

export const getFileAtHeadInput = z.object({
  directoryPath: z.string(),
  filePath: z.string(),
});
export const getFileAtHeadOutput = z.string().nullable();

export const diffInput = z.object({
  directoryPath: z.string(),
  ignoreWhitespace: z.boolean().optional(),
});
export const diffOutput = z.string();

export const getDiffStatsInput = directoryPathInput;
export const getDiffStatsOutput = diffStatsSchema;

export const stageFilesInput = z.object({
  directoryPath: z.string(),
  paths: z.array(z.string()),
});

export const getCurrentBranchInput = directoryPathInput;
export const getCurrentBranchOutput = z.string().nullable();

export const getAllBranchesInput = directoryPathInput;
export const getAllBranchesOutput = z.array(z.string());

export const gitBusyOperationSchema = z.enum([
  "rebase",
  "merge",
  "cherry-pick",
  "revert",
]);

export const gitBusyStateSchema = z.union([
  z.object({ busy: z.literal(false) }),
  z.object({
    busy: z.literal(true),
    operation: gitBusyOperationSchema,
  }),
]);

export const getGitBusyStateInput = directoryPathInput;
export const getGitBusyStateOutput = gitBusyStateSchema;

export const createBranchInput = z.object({
  directoryPath: z.string(),
  branchName: z.string(),
});

export const checkoutBranchInput = z.object({
  directoryPath: z.string(),
  branchName: z.string(),
});
export const checkoutBranchOutput = z.object({
  previousBranch: z.string(),
  currentBranch: z.string(),
});

export const discardFileChangesInput = z.object({
  directoryPath: z.string(),
  filePath: z.string(),
  fileStatus: gitFileStatusSchema,
});

export const getGitSyncStatusInput = directoryPathInput;
export const getGitSyncStatusOutput = gitSyncStatusSchema;

export const getLatestCommitInput = directoryPathInput;
export const getLatestCommitOutput = gitCommitInfoSchema.nullable();

export const getGitRepoInfoInput = directoryPathInput;
export const getGitRepoInfoOutput = gitRepoInfoSchema.nullable();

export const pushInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
  branch: z.string().optional(),
  setUpstream: z.boolean().default(false),
});

export type PushInput = z.infer<typeof pushInput>;

export const pullInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
  branch: z.string().optional(),
});

export type PullInput = z.infer<typeof pullInput>;

export const commitInput = z.object({
  directoryPath: z.string(),
  message: z.string(),
  paths: z.array(z.string()).optional(),
  allowEmpty: z.boolean().optional(),
  stagedOnly: z.boolean().optional(),
  taskId: z.string().optional(),
});

export type CommitInput = z.infer<typeof commitInput>;

export const gitStatusOutput = z.object({
  installed: z.boolean(),
  version: z.string().nullable(),
});

export type GitStatusOutput = z.infer<typeof gitStatusOutput>;

export const ghStatusOutput = z.object({
  installed: z.boolean(),
  version: z.string().nullable(),
  authenticated: z.boolean(),
  username: z.string().nullable(),
  error: z.string().nullable(),
});

export type GhStatusOutput = z.infer<typeof ghStatusOutput>;

export const ghAuthTokenOutput = z.object({
  success: z.boolean(),
  token: z.string().nullable(),
  error: z.string().nullable(),
});

export type GhAuthTokenOutput = z.infer<typeof ghAuthTokenOutput>;

export const prStatusInput = directoryPathInput;
export const prStatusOutput = z.object({
  hasRemote: z.boolean(),
  isGitHubRepo: z.boolean(),
  currentBranch: z.string().nullable(),
  defaultBranch: z.string().nullable(),
  prExists: z.boolean(),
  prUrl: z.string().nullable(),
  prState: z.string().nullable(),
  baseBranch: z.string().nullable(),
  headBranch: z.string().nullable(),
  isDraft: z.boolean().nullable(),
  error: z.string().nullable(),
});

export type PrStatusInput = z.infer<typeof prStatusInput>;
export type PrStatusOutput = z.infer<typeof prStatusOutput>;

export const getPrUrlForBranchInput = z.object({
  directoryPath: z.string(),
  branchName: z.string(),
});
export const getPrUrlForBranchOutput = z.string().nullable();

export type GetPrUrlForBranchInput = z.infer<typeof getPrUrlForBranchInput>;
export type GetPrUrlForBranchOutput = z.infer<typeof getPrUrlForBranchOutput>;

export const createPrInput = z.object({
  directoryPath: z.string(),
  flowId: z.string(),
  branchName: z.string().optional(),
  commitMessage: z.string().optional(),
  prTitle: z.string().optional(),
  prBody: z.string().optional(),
  draft: z.boolean().optional(),
  stagedOnly: z.boolean().optional(),
  taskId: z.string().optional(),
  conversationContext: z.string().optional(),
});

export type CreatePrInput = z.infer<typeof createPrInput>;

export const openPrInput = directoryPathInput;
export const openPrOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  prUrl: z.string().nullable(),
});

export type OpenPrInput = z.infer<typeof openPrInput>;
export type OpenPrOutput = z.infer<typeof openPrOutput>;

export const publishInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
});

export type PublishInput = z.infer<typeof publishInput>;

export const syncInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
});

export type SyncInput = z.infer<typeof syncInput>;

export const getPrTemplateInput = directoryPathInput;

export const getPrTemplateOutput = z.object({
  template: z.string().nullable(),
  templatePath: z.string().nullable(),
});

export type GetPrTemplateOutput = z.infer<typeof getPrTemplateOutput>;

export const getCommitConventionsInput = z.object({
  directoryPath: z.string(),
  sampleSize: z.number().default(20),
});

export const getCommitConventionsOutput = z.object({
  conventionalCommits: z.boolean(),
  commonPrefixes: z.array(z.string()),
  sampleMessages: z.array(z.string()),
});

export type GetCommitConventionsOutput = z.infer<
  typeof getCommitConventionsOutput
>;

export const getPrChangedFilesInput = z.object({
  prUrl: z.string(),
});
export const getPrChangedFilesOutput = z.array(changedFileSchema);

// getPrDiffStatsBatch schemas
//
// Beyond the diff numbers, the batch also carries the PR's live status
// (`state`/`merged`/`draft`) so list cards can render it from the single
// batched GraphQL request instead of firing one REST call per visible PR.
export const prDiffStatsSchema = z.object({
  additions: z.number(),
  deletions: z.number(),
  changedFiles: z.number(),
  /** Lowercased GitHub PR state. */
  state: z.enum(["open", "closed", "merged"]),
  merged: z.boolean(),
  draft: z.boolean(),
});
export type PrDiffStats = z.infer<typeof prDiffStatsSchema>;

export const getPrDiffStatsBatchInput = z.object({
  prUrls: z.array(z.string()),
});
export const getPrDiffStatsBatchOutput = z.record(
  z.string(),
  prDiffStatsSchema,
);

// getPrDetailsByUrl schemas
export const getPrDetailsByUrlInput = z.object({
  prUrl: z.string(),
});
export const getPrDetailsByUrlOutput = z.object({
  state: z.string(),
  merged: z.boolean(),
  draft: z.boolean(),
  headRefName: z.string().nullable(),
  title: z.string().nullable(),
});
export type PrDetailsByUrlOutput = z.infer<typeof getPrDetailsByUrlOutput>;

export {
  prActionTypeSchema,
  prReviewCommentSchema,
  prReviewCommentUserSchema,
  prReviewThreadSchema,
};
export type { PrActionType, PrReviewComment, PrReviewThread };

export const getPrReviewCommentsInput = z.object({
  prUrl: z.string(),
});
export const getPrReviewCommentsOutput = z.array(prReviewThreadSchema);

export const resolveReviewThreadInput = z.object({
  prUrl: z.string(),
  threadNodeId: z.string(),
  resolved: z.boolean(),
});
export const resolveReviewThreadOutput = z.object({
  success: z.boolean(),
  isResolved: z.boolean(),
});
export type ResolveReviewThreadOutput = z.infer<
  typeof resolveReviewThreadOutput
>;

export const replyToPrCommentInput = z.object({
  prUrl: z.string(),
  commentId: z.number(),
  body: z.string(),
});
export const replyToPrCommentOutput = z.object({
  success: z.boolean(),
  comment: prReviewCommentSchema.nullable(),
});
export type ReplyToPrCommentOutput = z.infer<typeof replyToPrCommentOutput>;

export const updatePrByUrlInput = z.object({
  prUrl: z.string(),
  action: prActionTypeSchema,
});
export const updatePrByUrlOutput = z.object({
  success: z.boolean(),
  message: z.string(),
});
export type UpdatePrByUrlOutput = z.infer<typeof updatePrByUrlOutput>;

export type {
  ApprovePrOutput,
  GetPrChecksOutput,
  GetPrCommentsOutput,
  MergePrOutput,
  PrCheck,
  PrCheckBucket,
  PrConversationComment,
  PrInfoByUrlOutput,
  PrMergeMethod,
} from "@posthog/shared";
// Native PR review schemas (PR overview, approve/merge, CI checks,
// conversation comments) are defined once in `@posthog/shared`'s git domain
// and re-exported here for the host router and UI.
export {
  approvePrInput,
  approvePrOutput,
  getPrChecksInput,
  getPrChecksOutput,
  getPrCommentsInput,
  getPrCommentsOutput,
  getPrInfoByUrlInput,
  getPrInfoByUrlOutput,
  mergePrInput,
  mergePrOutput,
  prCheckBucketSchema,
  prCheckSchema,
  prConversationCommentSchema,
  prMergeMethodSchema,
} from "@posthog/shared";

export const getBranchChangedFilesInput = z.object({
  repo: z.string(),
  branch: z.string(),
});
export const getBranchChangedFilesOutput = z.array(changedFileSchema);

export const getLocalBranchChangedFilesInput = z.object({
  directoryPath: z.string(),
  branch: z.string(),
});
export const getLocalBranchChangedFilesOutput = z.array(changedFileSchema);

export const generateCommitMessageInput = z.object({
  directoryPath: z.string(),
  conversationContext: z.string().optional(),
});

export const generateCommitMessageOutput = z.object({
  message: z.string(),
});

export const generatePrTitleAndBodyInput = z.object({
  directoryPath: z.string(),
  conversationContext: z.string().optional(),
});

export const generatePrTitleAndBodyOutput = z.object({
  title: z.string(),
  body: z.string(),
});

export const generatePrShortSummaryInput = z.object({
  conversationContext: z.string().optional(),
  prTitle: z.string().optional(),
});

export const generatePrShortSummaryOutput = z.object({
  summary: z.string(),
});

export const gitStateSnapshotSchema = z.object({
  changedFiles: z.array(changedFileSchema).optional(),
  diffStats: diffStatsSchema.optional(),
  syncStatus: gitSyncStatusSchema.optional(),
  latestCommit: gitCommitInfoSchema.nullable().optional(),
  prStatus: prStatusOutput.optional(),
});

export type GitStateSnapshot = z.infer<typeof gitStateSnapshotSchema>;

export const commitOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  commitSha: z.string().nullable(),
  branch: z.string().nullable(),
  state: gitStateSnapshotSchema.optional(),
});

export type CommitOutput = z.infer<typeof commitOutput>;

export const pushOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  state: gitStateSnapshotSchema.optional(),
});

export type PushOutput = z.infer<typeof pushOutput>;

export const pullOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  updatedFiles: z.number().optional(),
  state: gitStateSnapshotSchema.optional(),
});

export type PullOutput = z.infer<typeof pullOutput>;

export const publishOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  branch: z.string(),
  state: gitStateSnapshotSchema.optional(),
});

export type PublishOutput = z.infer<typeof publishOutput>;

export const syncOutput = z.object({
  success: z.boolean(),
  pullMessage: z.string(),
  pushMessage: z.string(),
  state: gitStateSnapshotSchema.optional(),
});

export type SyncOutput = z.infer<typeof syncOutput>;

export const createPrStep = z.enum([
  "creating-branch",
  "committing",
  "pushing",
  "creating-pr",
  "complete",
  "error",
]);

export type CreatePrStep = z.infer<typeof createPrStep>;

export const createPrOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  prUrl: z.string().nullable(),
  failedStep: createPrStep.nullable(),
  state: gitStateSnapshotSchema.optional(),
});

export type CreatePrOutput = z.infer<typeof createPrOutput>;

export const discardFileChangesOutput = z.object({
  success: z.boolean(),
  state: gitStateSnapshotSchema.optional(),
});

export type DiscardFileChangesOutput = z.infer<typeof discardFileChangesOutput>;

export {
  githubIssueSchema,
  githubIssueStateSchema,
  githubRefKindSchema,
  githubRefSchema,
  githubRefStateSchema,
};
export type {
  GitHubIssue,
  GithubIssueState,
  GithubPullRequest,
  GithubRef,
  GithubRefKind,
  GithubRefState,
};

export const searchGithubRefsInput = z.object({
  directoryPath: z.string(),
  query: z.string().optional(),
  limit: z.number().default(25),
  kinds: z.array(githubRefKindSchema).optional(),
});

export const searchGithubRefsOutput = z.array(githubRefSchema);

export const getGithubIssueInput = z.object({
  owner: z.string(),
  repo: z.string(),
  number: z.number().int().positive(),
});

export const getGithubIssueOutput = githubRefSchema.nullable();

export const getGithubPullRequestInput = getGithubIssueInput;

export const getGithubPullRequestOutput = getGithubIssueOutput;

export const createPrProgressPayload = z.object({
  flowId: z.string(),
  step: createPrStep,
  message: z.string(),
  prUrl: z.string().optional(),
});

export type CreatePrProgressPayload = z.infer<typeof createPrProgressPayload>;
