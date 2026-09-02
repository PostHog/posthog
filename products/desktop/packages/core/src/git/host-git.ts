import type { WorkspaceClient } from "@posthog/workspace-client/client";
import type {
  CloneProgressPayload,
  CreatePrInput,
  CreatePrOutput,
  CreatePrProgressPayload,
} from "./router-schemas";

export const GitServiceEvent = {
  CloneProgress: "cloneProgress",
  CreatePrProgress: "createPrProgress",
} as const;

export interface GitServiceEvents {
  [GitServiceEvent.CloneProgress]: CloneProgressPayload;
  [GitServiceEvent.CreatePrProgress]: CreatePrProgressPayload;
}

export interface HostGitService {
  cloneRepository(
    repoUrl: string,
    targetPath: string,
    cloneId: string,
  ): Promise<{ cloneId: string }>;
  createPr(input: CreatePrInput): Promise<CreatePrOutput>;
  toIterable<K extends keyof GitServiceEvents>(
    event: K,
    options: { signal?: AbortSignal },
  ): AsyncIterable<GitServiceEvents[K]>;
}

export interface HostGitWorkspaceClient {
  git: WorkspaceClient["git"];
}

export interface HostGitAgentService {
  getSessionEnvForTask(taskId: string): Promise<Record<string, string>>;
}

export interface GitPrWorkspaceInfo {
  mode: string;
  worktreePath?: string | null;
  folderPath?: string | null;
  linkedBranch?: string | null;
}

export interface GitWorkspaceLookup {
  getWorkspace(taskId: string): Promise<GitPrWorkspaceInfo | null>;
  linkBranch(taskId: string, branch: string, source: "user"): void;
}
