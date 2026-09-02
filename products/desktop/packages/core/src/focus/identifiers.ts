import { z } from "zod";

export const FOCUS_SERVICE = Symbol.for("posthog.core.focusService");

export const focusResultSchema = z.object({
  success: z.boolean(),
  error: z.string().optional(),
  stashPopWarning: z.string().optional(),
});

export type FocusResult = z.infer<typeof focusResultSchema>;

export const stashResultSchema = focusResultSchema.extend({
  stashRef: z.string().optional(),
});

export type StashResult = z.infer<typeof stashResultSchema>;

export const focusSessionSchema = z.object({
  mainRepoPath: z.string(),
  worktreePath: z.string(),
  branch: z.string(),
  originalBranch: z.string(),
  mainStashRef: z.string().nullable(),
  commitSha: z.string(),
});

export type FocusSession = z.infer<typeof focusSessionSchema>;

export const repoPathInput = z.object({ repoPath: z.string() });
export const mainRepoPathInput = z.object({ mainRepoPath: z.string() });
export const stashInput = z.object({
  repoPath: z.string(),
  message: z.string(),
});
export const checkoutInput = z.object({
  repoPath: z.string(),
  branch: z.string(),
});
export const worktreeInput = z.object({ worktreePath: z.string() });
export const reattachInput = z.object({
  worktreePath: z.string(),
  branch: z.string(),
});
export const syncInput = z.object({
  mainRepoPath: z.string(),
  worktreePath: z.string(),
});
export const findWorktreeInput = z.object({
  mainRepoPath: z.string(),
  branch: z.string(),
});

export const FocusServiceEvent = {
  BranchRenamed: "branchRenamed",
  ForeignBranchCheckout: "foreignBranchCheckout",
} as const;

export interface FocusServiceEvents {
  [FocusServiceEvent.BranchRenamed]: {
    mainRepoPath: string;
    worktreePath: string;
    oldBranch: string;
    newBranch: string;
  };
  [FocusServiceEvent.ForeignBranchCheckout]: {
    mainRepoPath: string;
    worktreePath: string;
    focusedBranch: string;
    foreignBranch: string;
  };
}

export interface IFocusService {
  getSession(mainRepoPath: string): FocusSession | null;
  saveSession(session: FocusSession): Promise<void>;
  deleteSession(mainRepoPath: string): Promise<void>;
  isFocusActive(mainRepoPath: string): boolean;
  validateFocusOperation(
    currentBranch: string | null,
    targetBranch: string,
  ): string | null;
  isDirty(repoPath: string): Promise<boolean>;
  getCommitSha(repoPath: string): Promise<string>;
  findWorktreeByBranch(
    mainRepoPath: string,
    branch: string,
  ): Promise<string | null>;
  toRelativeWorktreePath(absolutePath: string, mainRepoPath: string): string;
  toAbsoluteWorktreePath(relativePath: string): string;
  worktreeExistsAtPath(relativePath: string): Promise<boolean>;
  stash(repoPath: string, message: string): Promise<StashResult>;
  stashPop(repoPath: string): Promise<FocusResult>;
  stashApply(repoPath: string, stashRef: string): Promise<FocusResult>;
  checkout(repoPath: string, branch: string): Promise<FocusResult>;
  detachWorktree(worktreePath: string): Promise<FocusResult>;
  reattachWorktree(worktreePath: string, branch: string): Promise<FocusResult>;
  cleanWorkingTree(repoPath: string): Promise<void>;
  startSync(mainRepoPath: string, worktreePath: string): Promise<void>;
  stopSync(): Promise<void>;
  startWatchingMainRepo(mainRepoPath: string): Promise<void>;
  stopWatchingMainRepo(): Promise<void>;
  toIterable<K extends keyof FocusServiceEvents>(
    event: K,
    options: { signal?: AbortSignal },
  ): AsyncIterable<FocusServiceEvents[K]>;
}
