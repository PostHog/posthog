import { z } from "zod";

// PR review comment domain types. Shared between the git host service (which
// fetches them via the gh API) and the code-review UI (which renders them).
export const prReviewCommentUserSchema = z.object({
  login: z.string(),
  avatar_url: z.string(),
});

export const prReviewCommentSchema = z.object({
  id: z.number(),
  body: z.string(),
  path: z.string(),
  line: z.number().nullable(),
  original_line: z.number().nullable(),
  side: z.enum(["LEFT", "RIGHT"]),
  start_line: z.number().nullable(),
  start_side: z.enum(["LEFT", "RIGHT"]).nullable(),
  diff_hunk: z.string(),
  in_reply_to_id: z.number().nullish(),
  user: prReviewCommentUserSchema,
  created_at: z.string(),
  updated_at: z.string(),
  subject_type: z.enum(["line", "file"]).nullable(),
});

export type PrReviewComment = z.infer<typeof prReviewCommentSchema>;

export const prReviewThreadSchema = z.object({
  nodeId: z.string(),
  isResolved: z.boolean(),
  rootId: z.number(),
  filePath: z.string(),
  comments: z.array(prReviewCommentSchema),
});
export type PrReviewThread = z.infer<typeof prReviewThreadSchema>;

// GitHub ref (issue/PR) domain types. Shared between the git host service
// (gh search/lookup) and the message-editor issue chips + sidebar github refs.
export const githubRefKindSchema = z.enum(["issue", "pr"]);
export type GithubRefKind = z.infer<typeof githubRefKindSchema>;

export const githubRefStateSchema = z.enum(["OPEN", "CLOSED", "MERGED"]);
export type GithubRefState = z.infer<typeof githubRefStateSchema>;

export const githubRefSchema = z.object({
  kind: githubRefKindSchema,
  number: z.number(),
  title: z.string(),
  state: githubRefStateSchema,
  labels: z.array(z.string()),
  url: z.string(),
  repo: z.string(),
  isDraft: z.boolean().optional(),
});

export type GithubRef = z.infer<typeof githubRefSchema>;

// Legacy aliases kept so callers that previously consumed only issues continue to work.
export const githubIssueStateSchema = githubRefStateSchema;
export type GithubIssueState = GithubRefState;
export const githubIssueSchema = githubRefSchema;
export type GitHubIssue = GithubRef;
export type GithubPullRequest = GithubRef;

// PR action intent. Shared between the git host service (updatePrByUrl) and the
// git-interaction UI (PR status menu actions).
export const prActionTypeSchema = z.enum(["close", "reopen", "ready", "draft"]);
export type PrActionType = z.infer<typeof prActionTypeSchema>;

// Native PR review schemas (PR overview, approve/merge, CI checks,
// conversation comments). Defined once here and re-exported by
// `@posthog/core/git/router-schemas` and workspace-server's git schemas so
// the tRPC layers on both sides of the boundary share one source of truth.

/** Full PR overview (title/body/branches/stats) for the native in-app PR view. */
export const getPrInfoByUrlInput = z.object({ prUrl: z.string() });

export const getPrInfoByUrlOutput = z.object({
  number: z.number(),
  title: z.string(),
  body: z.string(),
  author: z.string().nullable(),
  state: z.string(),
  merged: z.boolean(),
  draft: z.boolean(),
  /** GitHub computes mergeability asynchronously; null until it settles. */
  mergeable: z.boolean().nullable(),
  /**
   * GitHub's `mergeable_state`: "clean" | "unstable" | "blocked" | "dirty" |
   * "behind" | "draft" | "unknown". "blocked" means branch protection forbids
   * the merge for this viewer — e.g. a required approving review is missing
   * (authors can't approve their own PRs) or required checks are failing.
   * Kept as a plain string so an undocumented value can't fail the parse.
   */
  mergeStateStatus: z.string().catch("unknown"),
  baseRefName: z.string().nullable(),
  headRefName: z.string().nullable(),
  additions: z.number(),
  deletions: z.number(),
  changedFiles: z.number(),
});

export type PrInfoByUrlOutput = z.infer<typeof getPrInfoByUrlOutput>;

export const approvePrInput = z.object({ prUrl: z.string() });

export const approvePrOutput = z.object({
  success: z.boolean(),
  message: z.string(),
});

export type ApprovePrOutput = z.infer<typeof approvePrOutput>;

export const prMergeMethodSchema = z.enum(["merge", "squash", "rebase"]);
export type PrMergeMethod = z.infer<typeof prMergeMethodSchema>;

export const mergePrInput = z.object({
  prUrl: z.string(),
  method: prMergeMethodSchema,
});

export const mergePrOutput = z.object({
  success: z.boolean(),
  message: z.string(),
});

export type MergePrOutput = z.infer<typeof mergePrOutput>;

// CI check runs / commit statuses for a PR, via `gh pr checks`.
export const prCheckBucketSchema = z.enum([
  "fail",
  "cancel",
  "pending",
  "pass",
  "skipping",
]);
export type PrCheckBucket = z.infer<typeof prCheckBucketSchema>;

export const prCheckSchema = z.object({
  name: z.string(),
  bucket: prCheckBucketSchema,
  link: z.string().nullable(),
  workflow: z.string().nullable(),
  description: z.string().nullable(),
});
export type PrCheck = z.infer<typeof prCheckSchema>;

export const getPrChecksInput = z.object({ prUrl: z.string() });
/** Null means the checks couldn't be fetched; [] means none reported. */
export const getPrChecksOutput = z.array(prCheckSchema).nullable();
export type GetPrChecksOutput = z.infer<typeof getPrChecksOutput>;

// Conversation (issue) comments and review summaries on a PR. Inline review
// comments live in `prReviewThreadSchema` above.
export const prConversationCommentSchema = z.object({
  id: z.number(),
  author: z.string(),
  avatarUrl: z.string().nullable(),
  body: z.string(),
  createdAt: z.string(),
  url: z.string().nullable(),
});
export type PrConversationComment = z.infer<typeof prConversationCommentSchema>;

export const getPrCommentsInput = z.object({ prUrl: z.string() });
/** Null means the comments couldn't be fetched; [] means none. */
export const getPrCommentsOutput = z
  .array(prConversationCommentSchema)
  .nullable();
export type GetPrCommentsOutput = z.infer<typeof getPrCommentsOutput>;
