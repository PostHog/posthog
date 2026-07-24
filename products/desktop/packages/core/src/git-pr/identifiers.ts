import type { SagaLogger } from "@posthog/shared";

export const GIT_PR_SERVICE = Symbol.for("posthog.core.gitPrService");
export const GIT_DIFF_SOURCE = Symbol.for("posthog.core.gitDiffSource");

export interface GitCommitConventions {
  conventionalCommits: boolean;
  commonPrefixes: string[];
  sampleMessages: string[];
}

export interface GitChangedFileSummary {
  status: string;
  path: string;
}

export interface GitCommitSummary {
  message: string;
}

export interface GitPrTemplate {
  template: string | null;
}

export interface GitDiffSource {
  getStagedDiff(directoryPath: string): Promise<string>;
  getUnstagedDiff(directoryPath: string): Promise<string>;
  getCommitConventions(directoryPath: string): Promise<GitCommitConventions>;
  getChangedFilesHead(directoryPath: string): Promise<GitChangedFileSummary[]>;
  getDefaultBranch(directoryPath: string): Promise<string>;
  getCurrentBranch(directoryPath: string): Promise<string | null>;
  getDiffAgainstRemote(
    directoryPath: string,
    baseBranch: string,
  ): Promise<string>;
  getCommitsBetweenBranches(
    directoryPath: string,
    baseBranch: string,
    head: string | undefined,
    limit: number,
  ): Promise<GitCommitSummary[]>;
  getPrTemplate(directoryPath: string): Promise<GitPrTemplate>;
  fetchFromRemote(directoryPath: string): Promise<void>;
}

export interface GitPrLogger extends SagaLogger {}

export interface CreatePrInput {
  directoryPath: string;
  branchName?: string;
  commitMessage?: string;
  prTitle?: string;
  prBody?: string;
  draft?: boolean;
  stagedOnly?: boolean;
  taskId?: string;
  conversationContext?: string;
}

export interface CreatePrResult {
  success: boolean;
  message: string;
  prUrl: string | null;
  failedStep: string | null;
  state?: unknown;
}

export interface CreatePrHost {
  getSessionEnvForTask(
    taskId: string | undefined,
  ): Promise<Record<string, string> | undefined>;
  getCurrentBranch(directoryPath: string): Promise<string | null>;
  createBranch(directoryPath: string, name: string): Promise<void>;
  getChangedFilesHead(directoryPath: string): Promise<readonly unknown[]>;
  getHeadSha(directoryPath: string): Promise<string>;
  commit(
    directoryPath: string,
    message: string,
    options: {
      stagedOnly?: boolean;
      taskId?: string;
      env?: Record<string, string>;
    },
  ): Promise<{ success: boolean; message: string }>;
  resetSoft(directoryPath: string, sha: string): Promise<void>;
  getSyncStatus(directoryPath: string): Promise<{ hasRemote: boolean }>;
  push(
    directoryPath: string,
    env?: Record<string, string>,
  ): Promise<{ success: boolean; message: string }>;
  publish(
    directoryPath: string,
    env?: Record<string, string>,
  ): Promise<{ success: boolean; message: string }>;
  createPrViaGh(
    directoryPath: string,
    title?: string,
    body?: string,
    draft?: boolean,
    env?: Record<string, string>,
  ): Promise<{ success: boolean; message: string; prUrl: string | null }>;
  linkBranch(taskId: string, branch: string, source: "user"): void;
  getPrState(directoryPath: string): Promise<unknown>;
}
