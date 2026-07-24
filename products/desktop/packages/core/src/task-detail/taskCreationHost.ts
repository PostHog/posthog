import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { CloudSkillBundleRef } from "@posthog/core/sessions/cloudArtifactIdentifiers";
import type { Workspace, WorkspaceInfo, WorkspaceMode } from "@posthog/shared";
import type { TaskCreationApiClient } from "./taskCreationApiClient";

export interface CloudPromptTransport {
  filePaths: string[];
  skillBundles: CloudSkillBundleRef[];
  messageText?: string;
  promptText: string;
}

export interface CreateWorkspaceArgs {
  taskId: string;
  mainRepoPath: string;
  folderId: string;
  folderPath: string;
  mode: WorkspaceMode;
  branch?: string;
  allowRemoteBranchCheckout?: boolean;
  reuseExistingWorktree?: boolean;
}

export type CreatedWorkspaceInfo = WorkspaceInfo;

export interface TaskFolderInfo {
  id: string;
  path: string;
}

export interface DetectedRepo {
  organization: string;
  repository: string;
}

export interface TaskEnvironment {
  name: string;
  setup?: { script?: string | null } | null;
}

export interface SetupActionDispatch {
  taskId: string;
  command: string;
  cwd: string;
  label: string;
}

export interface ClaudeCliImportFingerprint {
  sourceMtimeMs: number;
  sourceSizeBytes: number;
  sourceLastEntryUuid: string | null;
}

export interface ImportedClaudeCliSession {
  importedSessionId: string;
  fingerprint: ClaudeCliImportFingerprint;
}

export interface RecordClaudeCliImportArgs {
  sourceSessionId: string;
  importedSessionId: string;
  repoPath: string;
  taskId: string;
  fingerprint: ClaudeCliImportFingerprint;
}

export interface ITaskCreationHost {
  getAuthenticatedClient(): Promise<TaskCreationApiClient | null>;
  assertCloudUsageAvailable(): Promise<void>;
  getTaskDirectory(taskId: string, repoKey?: string): Promise<string | null>;
  /**
   * Ensure a per-task scratch working directory exists for a repo-less channel
   * task. Returns its absolute path so the agent session can start there.
   */
  ensureScratchDir(taskId: string): Promise<string>;
  getWorkspace(taskId: string): Promise<Workspace | null>;
  createWorkspace(args: CreateWorkspaceArgs): Promise<CreatedWorkspaceInfo>;
  deleteWorkspace(args: {
    taskId: string;
    mainRepoPath: string;
  }): Promise<void>;
  getFolders(): Promise<TaskFolderInfo[]>;
  addFolder(args: { folderPath: string }): Promise<TaskFolderInfo>;
  addAdditionalDirectory(args: { taskId: string; path: string }): Promise<void>;
  removeAdditionalDirectory(args: {
    taskId: string;
    path: string;
  }): Promise<void>;
  getEnvironment(args: {
    repoPath: string;
    id: string;
  }): Promise<TaskEnvironment | null>;
  detectRepo(args: { directoryPath: string }): Promise<DetectedRepo | null>;
  getCloudPromptTransport(
    prompt: string | ContentBlock[],
    filePaths?: string[],
  ): CloudPromptTransport;
  /**
   * Rewrite a leading local-skill slash command (e.g. `/my-skill args`) into a
   * `<skill .../>` tag so its bundle is uploaded on the first cloud message.
   * Returns the prompt unchanged when it isn't a local-skill invocation. The
   * follow-up message path already does this; the initial-creation path must
   * too, or a typed `/my-skill` reaches the sandbox with no bundle attached.
   */
  resolveLocalSkillCommandPrompt(prompt: string): Promise<string>;
  /**
   * Return-and-clear the pre-warmed sandbox lease matching the composer
   * selection, if one was provisioned while the user typed. The saga uploads
   * first-message attachments (skill bundles, files) to this run before
   * createTask so the backend's warm activation can forward them; null means
   * no warm run is known client-side.
   */
  takeWarmTaskLease(args: {
    repository: string;
    branch?: string | null;
    runtimeAdapter?: string | null;
    model?: string | null;
    reasoningEffort?: string | null;
    sandboxEnvironmentId?: string | null;
    customImageId?: string | null;
  }): { taskId: string; runId: string } | null;
  uploadRunAttachments(
    client: TaskCreationApiClient,
    taskId: string,
    runId: string,
    filePaths: string[],
    skillBundles?: CloudSkillBundleRef[],
  ): Promise<string[]>;
  setProvisioningActive(taskId: string): void;
  clearProvisioning(taskId: string): void;
  dispatchSetupAction(args: SetupActionDispatch): void;
  track(event: string, props?: Record<string, unknown>): void;
  importClaudeCliSession(args: {
    repoPath: string;
    sourceSessionId: string;
  }): Promise<ImportedClaudeCliSession>;
  /** Compensate the import step: remove the copied transcript on rollback. */
  deleteClaudeCliImport(args: {
    repoPath: string;
    importedSessionId: string;
  }): Promise<void>;
  recordClaudeCliImport(args: RecordClaudeCliImportArgs): Promise<void>;
  /** Compensate the record step: drop the tracking row on rollback. */
  deleteClaudeCliImportRecord(args: {
    importedSessionId: string;
  }): Promise<void>;
  /**
   * Link the task to the branch the imported session worked on, without
   * checking it out. Lets the standard branch-mismatch prompt surface if the
   * local checkout is on a different branch.
   */
  linkTaskBranch(args: { taskId: string; branchName: string }): Promise<void>;
}
