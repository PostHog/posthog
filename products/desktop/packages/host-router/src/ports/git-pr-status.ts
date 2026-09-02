import type {
  CachedPrUrlOutput,
  TaskPrStatus,
} from "@posthog/workspace-server/services/workspace/schemas";

export const GIT_PR_STATUS_PROVIDER = Symbol.for(
  "posthog.host.gitPrStatusProvider",
);

export interface IGitPrStatus {
  getTaskPrStatus(
    taskId: string,
    cloudPrUrl: string | null,
  ): Promise<TaskPrStatus>;
  getCachedPrUrl(taskId: string): CachedPrUrlOutput;
  setPrimaryPrUrl(taskId: string, prUrl: string): Promise<void>;
}
