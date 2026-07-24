import { buildCloudTaskDescription } from "@posthog/core/editor/cloud-prompt";
import type {
  Adapter,
  AgentRuntime,
  CloudMcpServerImport,
  CloudMcpServerRelayDesignation,
  TaskCreationInput,
  WorkspaceMode,
} from "@posthog/shared";
import type { ExecutionMode } from "@posthog/shared/domain-types";

export interface PrepareTaskInputOptions {
  selectedDirectory?: string;
  selectedRepository?: string | null;
  githubIntegrationId?: number;
  githubUserIntegrationId?: string;
  workspaceMode: WorkspaceMode;
  branch?: string | null;
  allowRemoteBranchCheckout?: boolean;
  reuseExistingWorktree?: boolean;
  executionMode?: ExecutionMode;
  adapter?: Adapter;
  runtime?: AgentRuntime;
  model?: string;
  reasoningLevel?: string;
  environmentId?: string | null;
  sandboxEnvironmentId?: string;
  customImageId?: string;
  signalReportId?: string;
  additionalDirectories?: string[];
  channelContext?: string;
  channelName?: string;
  channelId?: string;
  channelContextId?: string;
  customInstructions?: string;
  autoPublishCloudRuns?: boolean;
  rtkEnabledCloud?: boolean;
  allowNoRepo?: boolean;
  importedMcpServers?: CloudMcpServerImport[];
  relayedMcpServers?: CloudMcpServerRelayDesignation[];
}

export function prepareTaskInput(
  serializedContent: string,
  filePaths: string[],
  options: PrepareTaskInputOptions,
): TaskCreationInput {
  const isCloud = options.workspaceMode === "cloud";
  return {
    content: serializedContent,
    taskDescription: isCloud
      ? buildCloudTaskDescription(serializedContent, filePaths)
      : undefined,
    filePaths,
    repoPath: isCloud ? undefined : options.selectedDirectory,
    repository: isCloud ? options.selectedRepository : undefined,
    githubIntegrationId: options.githubIntegrationId,
    githubUserIntegrationId: options.githubUserIntegrationId,
    workspaceMode: options.workspaceMode,
    branch: options.branch,
    allowRemoteBranchCheckout: options.allowRemoteBranchCheckout,
    reuseExistingWorktree: options.reuseExistingWorktree,
    executionMode: options.executionMode,
    adapter: options.adapter,
    runtime: options.runtime ?? "acp",
    model: options.model,
    reasoningLevel: options.reasoningLevel,
    environmentId: options.environmentId ?? undefined,
    sandboxEnvironmentId: options.sandboxEnvironmentId,
    customImageId: options.customImageId,
    cloudPrAuthorshipMode:
      options.signalReportId && isCloud ? "user" : undefined,
    cloudRunSource:
      options.signalReportId && isCloud ? "signal_report" : undefined,
    cloudAutoPublish: isCloud ? options.autoPublishCloudRuns : undefined,
    cloudRtkEnabled: isCloud ? options.rtkEnabledCloud : undefined,
    signalReportId: options.signalReportId,
    additionalDirectories: isCloud ? undefined : options.additionalDirectories,
    channelContext: options.channelContext,
    channelName: options.channelName,
    channelId: options.channelId,
    channelContextId: options.channelContextId,
    customInstructions: isCloud ? options.customInstructions : undefined,
    allowNoRepo: options.allowNoRepo,
    importedMcpServers: isCloud ? options.importedMcpServers : undefined,
    relayedMcpServers: isCloud ? options.relayedMcpServers : undefined,
  };
}

/**
 * Input for starting a task from an existing task-less worktree (the sidebar's
 * one-click adoption). No content: the agent session starts idle and the user
 * types the first message in the opened chat. The branch doubles as the task
 * description so the task is named after it.
 */
export function buildWorktreeAdoptionInput(options: {
  repoPath: string;
  branch: string;
}): TaskCreationInput {
  return {
    taskDescription: options.branch,
    repoPath: options.repoPath,
    workspaceMode: "worktree",
    branch: options.branch,
    reuseExistingWorktree: true,
  };
}

const ERROR_TITLES: Record<string, string> = {
  repo_detection: "Failed to detect repository",
  task_creation: "Failed to create task",
  workspace_creation: "Failed to create workspace",
  cloud_prompt_preparation: "Failed to prepare cloud attachments",
  cloud_run: "Failed to start cloud execution",
  agent_session: "Failed to start agent session",
};

export function getErrorTitle(failedStep: string): string {
  return ERROR_TITLES[failedStep] ?? "Task creation failed";
}
