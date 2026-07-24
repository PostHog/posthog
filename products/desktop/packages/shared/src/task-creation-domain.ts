import type { Adapter } from "./adapter";
import type { AgentRuntime } from "./agent-runtime";
import type { CloudRunSource, PrAuthorshipMode } from "./cloud";
import type { Task } from "./domain-types";
import type { ExecutionMode } from "./exec-types";
import type {
  CloudMcpServerImport,
  CloudMcpServerRelayDesignation,
} from "./local-mcp-domain";
import type { WorkspaceMode } from "./workspace";
import type { Workspace } from "./workspace-domain";

// Host-agnostic input/output for the task-creation flow. The renderer
// TaskCreationSaga owns the orchestration; these are the plain data shapes its
// consumers (inbox direct-create hooks, deep-link open, task-input) pass and
// receive. Lives in shared so packages/ui can consume them without importing
// the renderer saga.
export interface TaskCreationInput {
  // For opening existing task
  taskId?: string;
  // For creating new task (required if no taskId)
  content?: string;
  taskDescription?: string;
  filePaths?: string[];
  repoPath?: string;
  repository?: string | null;
  workspaceMode?: WorkspaceMode;
  branch?: string | null;
  // When the branch exists only on the remote, opt in to fetching and checking
  // it out locally into the worktree (set after the user confirms).
  allowRemoteBranchCheckout?: boolean;
  // When a worktree is already checked out on the branch, opt in to reusing it
  // for this task instead of creating a new one (set after the user confirms).
  reuseExistingWorktree?: boolean;
  githubIntegrationId?: number;
  githubUserIntegrationId?: string;
  executionMode?: ExecutionMode;
  adapter?: Adapter;
  runtime?: AgentRuntime;
  model?: string;
  reasoningLevel?: string;
  environmentId?: string;
  sandboxEnvironmentId?: string;
  customImageId?: string;
  cloudPrAuthorshipMode?: PrAuthorshipMode;
  cloudRunSource?: CloudRunSource;
  /**
   * When true, the cloud run agent pushes its work and opens a draft PR on
   * completion without waiting for an explicit ask (Settings → Advanced).
   */
  cloudAutoPublish?: boolean;
  /**
   * rtk command-output compression for the cloud run. Only false is
   * meaningful: it opts the run out of the server-side default (enabled).
   */
  cloudRtkEnabled?: boolean;
  signalReportId?: string;
  additionalDirectories?: string[];
  /**
   * CONTEXT.md of the channel a task was created in, if any. Appended to the
   * agent's initial prompt as optional background — reference material the
   * agent may draw on, not instructions it must follow.
   */
  channelContext?: string;
  /** Display name of that channel, embedded in the context block for the UI. */
  channelName?: string;
  /** Backend channel UUID the created task is owned by (its feed home). */
  channelId?: string;
  /**
   * Desktop file-system folder id that owns this channel's CONTEXT.md (the
   * `/website/$channelId` id — distinct from the backend feed `channelId`
   * above). When set, the injected context tells the agent to publish upkeep
   * corrections to this exact id via the PostHog MCP, rather than resolving the
   * channel by display name.
   */
  channelContextId?: string;
  /**
   * The user's saved personalization (Settings → Personalization custom
   * instructions). Cloud-only: local tasks already receive these through the
   * workspace-server system prompt, so the saga folds this into the cloud run's
   * first message instead, to avoid double-injecting.
   */
  customInstructions?: string;
  /**
   * Local (~/.claude.json) MCP servers classified as importable, forwarded to
   * the cloud sandbox in the run-creation payload. Cloud-only; local sessions
   * already read the user's config directly.
   */
  importedMcpServers?: CloudMcpServerImport[];
  /**
   * Desktop-only local MCP servers (stdio / private URL) designated for
   * relaying into the cloud run via the creating desktop
   * (docs/cloud-mcp-relay.md). Names only. Cloud-only.
   */
  relayedMcpServers?: CloudMcpServerRelayDesignation[];
  /**
   * When true, the task may be created without a repo/branch. Used by the
   * channels "generic chat box": the agent decides at runtime whether it needs
   * a repo and attaches one lazily. A local session still starts, in a scratch
   * working directory, so non-code tasks (analysis, email) can run repo-less.
   */
  allowNoRepo?: boolean;
  /**
   * Continue a Claude Code CLI session by importing its transcript and resuming
   * with replay. Local mode only; forces the claude adapter. `branch` is what the
   * session last worked on, linked so the branch-mismatch prompt can fire.
   */
  importedClaudeSession?: { sourceSessionId: string; branch?: string | null };
}

export interface TaskCreationOutput {
  task: Task;
  workspace: Workspace | null;
  /**
   * Set when worktree provisioning failed but the task was kept (not rolled
   * back) so the user can retry setup on the existing task. The saga returns a
   * partial success in this case; consumers surface the error and keep the user
   * on the task rather than reopening the composer.
   */
  provisioningError?: string;
}
