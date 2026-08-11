import type { TaskSessionStorageAccess } from "@posthog/api-client/posthog-client";
import type {
  Adapter,
  CloudMcpServerRelayDesignation,
  CloudRunSource,
  McpServerConnection,
  PrAuthorshipMode,
} from "@posthog/shared";
import type { Task, TaskRun } from "@posthog/shared/domain-types";

export interface CreateTaskRunClientOptions {
  environment?: "local" | "cloud";
  mode?: "interactive" | "background";
  branch?: string | null;
  adapter?: Adapter;
  piRuntime?: boolean;
  model?: string;
  reasoningLevel?: string;
  contextWindow?: "200k" | "1m";
  fastMode?: boolean;
  sandboxEnvironmentId?: string;
  customImageId?: string;
  prAuthorshipMode?: PrAuthorshipMode;
  autoPublish?: boolean;
  rtkEnabled?: boolean;
  runSource?: CloudRunSource;
  signalReportId?: string;
  initialPermissionMode?: string;
  importedMcpServers?: McpServerConnection[];
  relayedMcpServers?: CloudMcpServerRelayDesignation[];
}

export interface StartTaskRunClientOptions {
  pendingUserMessage?: string;
  pendingUserArtifactIds?: string[];
}

export interface TaskCreationApiClient {
  getTask(taskId: string): Promise<Task>;
  getTaskRun(taskId: string, runId: string): Promise<TaskRun>;
  createTask(options: Record<string, unknown>): Promise<unknown>;
  deleteTask(taskId: string): Promise<void>;
  createTaskRun(
    taskId: string,
    options?: CreateTaskRunClientOptions,
  ): Promise<TaskRun>;
  startTaskRun(
    taskId: string,
    runId: string,
    options?: StartTaskRunClientOptions,
  ): Promise<Task>;
  getTaskSessionStorageAccess(
    taskId: string,
    runId: string,
  ): Promise<TaskSessionStorageAccess | null>;
  resumeRunInCloud(taskId: string, runId: string): Promise<TaskRun>;
}
