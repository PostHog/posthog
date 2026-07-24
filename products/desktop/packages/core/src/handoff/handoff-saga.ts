import {
  type Adapter,
  type GitHandoffCheckpoint,
  type HandoffLocalGitState,
  Saga,
  type SagaLogger,
} from "@posthog/shared";
import type { HandoffBaseDeps, HandoffSagaInput } from "./types";

export type { HandoffSagaInput } from "./types";

export interface HandoffSagaOutput {
  sessionId: string;
  checkpointApplied: boolean;
  conversationTurns: number;
}

export interface HandoffResumeState {
  conversation: unknown[];
  latestGitCheckpoint: GitHandoffCheckpoint | null;
}

export interface HandoffSagaDeps extends HandoffBaseDeps {
  markRunEnvironmentLocal(taskId: string, runId: string): Promise<void>;
  fetchResumeState(
    taskId: string,
    runId: string,
  ): Promise<{ resumeState: HandoffResumeState; cloudLogUrl: string | null }>;
  formatConversation(conversation: unknown[]): string;
  applyGitCheckpoint(
    checkpoint: GitHandoffCheckpoint,
    repoPath: string,
    taskId: string,
    runId: string,
    localGitState?: HandoffLocalGitState,
  ): Promise<void>;
  reconnectSession(params: {
    taskId: string;
    taskRunId: string;
    repoPath: string;
    apiHost: string;
    projectId: number;
    logUrl: string;
    sessionId?: string;
    adapter?: Adapter;
  }): Promise<{ sessionId: string } | null>;
  closeCloudRun(
    taskId: string,
    runId: string,
    apiHost: string,
    teamId: number,
    localGitState?: HandoffLocalGitState,
  ): Promise<void>;
  attachWorkspaceToFolder(
    taskId: string,
    repoPath: string,
  ): { revert: () => void };
  seedLocalLogs(runId: string, logUrl: string): Promise<void>;
  setPendingContext(taskRunId: string, context: string): void;
}

export class HandoffSaga extends Saga<HandoffSagaInput, HandoffSagaOutput> {
  readonly sagaName = "HandoffSaga";
  private deps: HandoffSagaDeps;

  constructor(deps: HandoffSagaDeps, logger?: SagaLogger) {
    super(logger);
    this.deps = deps;
  }

  protected async execute(input: HandoffSagaInput): Promise<HandoffSagaOutput> {
    const { taskId, runId, repoPath, apiHost, teamId } = input;

    this.deps.onProgress(
      "fetching_logs",
      "Closing cloud run and capturing snapshot...",
    );

    await this.readOnlyStep("close_cloud_run", async () => {
      await this.deps.closeCloudRun(
        taskId,
        runId,
        apiHost,
        teamId,
        input.localGitState,
      );
    });

    await this.readOnlyStep("update_run_environment", async () => {
      await this.deps.markRunEnvironmentLocal(taskId, runId);
    });

    const { resumeState, cloudLogUrl } = await this.readOnlyStep(
      "fetch_and_rebuild",
      async () => {
        const { resumeState: state, cloudLogUrl: logUrl } =
          await this.deps.fetchResumeState(taskId, runId);
        return { resumeState: state, cloudLogUrl: logUrl };
      },
    );

    let checkpointApplied = false;
    const checkpoint = resumeState.latestGitCheckpoint;
    if (checkpoint) {
      this.deps.onProgress(
        "applying_git_checkpoint",
        "Applying cloud git state locally...",
      );

      await this.step({
        name: "apply_git_checkpoint",
        execute: async () => {
          await this.deps.applyGitCheckpoint(
            checkpoint,
            repoPath,
            taskId,
            runId,
            input.localGitState,
          );
          checkpointApplied = true;
        },
        rollback: async () => {},
      });
    }

    await this.step<{ revert: () => void }>({
      name: "attach_workspace_to_folder",
      execute: async () => this.deps.attachWorkspaceToFolder(taskId, repoPath),
      rollback: async ({ revert }) => {
        revert();
      },
    });

    if (cloudLogUrl) {
      await this.step({
        name: "seed_local_logs",
        execute: async () => {
          await this.deps.seedLocalLogs(runId, cloudLogUrl);
        },
        rollback: async () => {},
      });
    }

    this.deps.onProgress("spawning_agent", "Starting local agent...");

    let agentSessionId = "";
    await this.step({
      name: "spawn_agent",
      execute: async () => {
        const response = await this.deps.reconnectSession({
          taskId,
          taskRunId: runId,
          repoPath,
          apiHost,
          projectId: teamId,
          logUrl: cloudLogUrl ?? "",
          sessionId: input.sessionId,
          adapter: input.adapter,
        });
        if (!response) {
          throw new Error("Failed to create local agent session");
        }
        agentSessionId = response.sessionId;
      },
      rollback: async () => {
        await this.deps.killSession(runId).catch(() => {});
      },
    });

    await this.readOnlyStep("set_context", async () => {
      const context = this.buildHandoffContext(
        resumeState.conversation,
        checkpointApplied,
      );
      this.deps.setPendingContext(runId, context);
    });

    this.deps.onProgress("complete", "Handoff complete");

    return {
      sessionId: agentSessionId,
      checkpointApplied,
      conversationTurns: resumeState.conversation.length,
    };
  }

  private buildHandoffContext(
    conversation: unknown[],
    checkpointApplied: boolean,
  ): string {
    const conversationSummary = this.deps.formatConversation(conversation);

    const fileStatus = checkpointApplied
      ? "The workspace git state and files have been restored from the cloud session checkpoint."
      : "The workspace from the cloud session could not be restored from a checkpoint. You are working with the local file state.";

    return (
      `You are resuming a previous conversation that was running in a cloud sandbox. ` +
      `The user has transferred you to their local machine. ${fileStatus}\n\n` +
      `Here is the conversation history from the cloud session:\n\n` +
      `${conversationSummary}\n\n` +
      `The user will now send you a message. Respond to it with full context from the session above.`
    );
  }
}
