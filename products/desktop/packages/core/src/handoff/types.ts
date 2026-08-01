import type {
  Adapter,
  HandoffLocalGitState,
  WorkspaceMode,
} from "@posthog/shared";

export type HandoffStep =
  | "fetching_logs"
  | "applying_git_checkpoint"
  | "spawning_agent"
  | "capturing_checkpoint"
  | "stopping_agent"
  | "starting_cloud_run"
  | "complete"
  | "failed";

export interface HandoffSagaInput {
  taskId: string;
  runId: string;
  repoPath: string;
  apiHost: string;
  teamId: number;
  sessionId?: string;
  adapter?: Adapter;
  localGitState?: HandoffLocalGitState;
}

export interface HandoffToCloudSagaInput {
  taskId: string;
  runId: string;
  repoPath: string;
  apiHost: string;
  teamId: number;
  localGitState?: HandoffLocalGitState;
}

export interface HandoffBaseDeps {
  killSession(taskRunId: string): Promise<void>;
  updateWorkspaceMode(taskId: string, mode: WorkspaceMode): void;
  onProgress(step: HandoffStep, message: string): void;
}
