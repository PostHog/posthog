import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type HandoffHost,
  type SagaLogger,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { CloudTaskService } from "../cloud-task/cloud-task";
import { CLOUD_TASK_SERVICE } from "../cloud-task/identifiers";
import { HandoffSaga, type HandoffSagaDeps } from "./handoff-saga";
import {
  HandoffToCloudSaga,
  type HandoffToCloudSagaDeps,
} from "./handoff-to-cloud-saga";
import { HANDOFF_HOST } from "./identifiers";
import {
  type HandoffErrorCode,
  HandoffEvent,
  type HandoffExecuteInput,
  type HandoffExecuteResult,
  type HandoffPreflightInput,
  type HandoffPreflightResult,
  type HandoffServiceEvents,
  type HandoffToCloudExecuteInput,
  type HandoffToCloudExecuteResult,
  type HandoffToCloudPreflightInput,
  type HandoffToCloudPreflightResult,
} from "./schemas";

const GITHUB_AUTHORIZATION_REQUIRED_CODE = "github_authorization_required";
const GITHUB_AUTHORIZATION_REQUIRED_MESSAGE =
  "Connect GitHub in your browser, then retry Continue in cloud.";

export function extractHandoffErrorCode(
  message: string | undefined,
): HandoffErrorCode | undefined {
  if (message?.includes(GITHUB_AUTHORIZATION_REQUIRED_CODE)) {
    return GITHUB_AUTHORIZATION_REQUIRED_CODE;
  }
  return undefined;
}

@injectable()
export class HandoffService extends TypedEventEmitter<HandoffServiceEvents> {
  private readonly logger: SagaLogger;

  constructor(
    @inject(HANDOFF_HOST)
    private readonly host: HandoffHost,
    @inject(CLOUD_TASK_SERVICE)
    private readonly cloudTaskService: CloudTaskService,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    super();
    this.logger = rootLogger.scope("handoff");
  }

  async preflight(
    input: HandoffPreflightInput,
  ): Promise<HandoffPreflightResult> {
    const { repoPath } = input;

    let localTreeDirty = false;
    let localGitState: HandoffPreflightResult["localGitState"];
    let changedFileDetails: HandoffPreflightResult["changedFiles"];
    try {
      const changedFiles = await this.host.getChangedFiles(repoPath);
      localTreeDirty = changedFiles.length > 0;
      changedFileDetails = changedFiles.map((f) => ({
        path: f.path,
        status: f.status,
        linesAdded: f.linesAdded,
        linesRemoved: f.linesRemoved,
      }));
      localGitState = await this.host.getLocalGitState(repoPath);
    } catch (err) {
      this.logger.warn("Failed to check local working tree", { repoPath, err });
    }

    const canHandoff = !localTreeDirty;
    const reason = localTreeDirty
      ? "Local working tree has uncommitted changes. Commit or stash them first."
      : undefined;

    return {
      canHandoff,
      reason,
      localTreeDirty,
      localGitState,
      changedFiles: changedFileDetails,
    };
  }

  async execute(input: HandoffExecuteInput): Promise<HandoffExecuteResult> {
    const ctx = { apiHost: input.apiHost, teamId: input.teamId };

    const deps: HandoffSagaDeps = {
      markRunEnvironmentLocal: (taskId, runId) =>
        this.host.markRunEnvironmentLocal(ctx, taskId, runId),

      fetchResumeState: (taskId, runId) =>
        this.host.fetchResumeState(ctx, taskId, runId),

      formatConversation: (conversation) =>
        this.host.formatConversation(conversation),

      applyGitCheckpoint: (
        checkpoint,
        repoPath,
        taskId,
        runId,
        localGitState,
      ) =>
        this.host.applyGitCheckpoint(
          ctx,
          checkpoint,
          repoPath,
          taskId,
          runId,
          localGitState,
        ),

      closeCloudRun: async (taskId, runId, apiHost, teamId, localGitState) => {
        const result = await this.cloudTaskService.sendCommand({
          taskId,
          runId,
          apiHost,
          teamId,
          method: "close",
          params: localGitState ? { localGitState } : undefined,
        });
        if (!result.success) {
          this.logger.warn("Close command failed, continuing with handoff", {
            error: result.error,
          });
        }
      },

      updateWorkspaceMode: (taskId, mode) =>
        this.host.updateWorkspaceMode(taskId, mode),

      attachWorkspaceToFolder: (taskId, repoPath) =>
        this.host.attachWorkspaceToFolder(taskId, repoPath),

      seedLocalLogs: (runId, logUrl) => this.host.seedLocalLogs(runId, logUrl),

      reconnectSession: (params) => this.host.reconnectSession(params),

      killSession: (taskRunId) => this.host.killSession(taskRunId),

      setPendingContext: (taskRunId, context) =>
        this.host.setPendingContext(taskRunId, context),

      onProgress: (step, message) => {
        this.emit(HandoffEvent.Progress, {
          taskId: input.taskId,
          step,
          message,
        });
      },
    };

    const saga = new HandoffSaga(deps, this.logger);
    const result = await saga.run(input);

    if (!result.success) {
      this.logger.error("Handoff saga failed", {
        error: result.error,
        failedStep: result.failedStep,
      });
      deps.onProgress("failed", result.error ?? "Handoff failed");
      return {
        success: false,
        error: `Handoff failed at step '${result.failedStep}': ${result.error}`,
      };
    }

    return {
      success: true,
      sessionId: result.data.sessionId,
    };
  }

  async preflightToCloud(
    input: HandoffToCloudPreflightInput,
  ): Promise<HandoffToCloudPreflightResult> {
    const { repoPath } = input;

    let localGitState: HandoffToCloudPreflightResult["localGitState"];
    try {
      localGitState = await this.host.getLocalGitState(repoPath);
    } catch (err) {
      this.logger.warn("Failed to read local git state for cloud handoff", {
        repoPath,
        err,
      });
    }

    return { canHandoff: true, localGitState };
  }

  async executeToCloud(
    input: HandoffToCloudExecuteInput,
  ): Promise<HandoffToCloudExecuteResult> {
    const { taskId, runId, repoPath, apiHost, teamId } = input;
    const ctx = { apiHost, teamId };

    const deps: HandoffToCloudSagaDeps = {
      captureGitCheckpoint: (localGitState) =>
        this.host.captureGitCheckpoint(
          ctx,
          repoPath,
          taskId,
          runId,
          localGitState,
        ),

      persistCheckpointToLog: (checkpoint) =>
        this.host.persistCheckpointToLog(ctx, taskId, runId, checkpoint),

      countLocalLogEntries: (taskRunId) =>
        this.host.countLocalLogEntries(taskRunId),

      resumeRunInCloud: () => this.host.resumeRunInCloud(ctx, taskId, runId),

      killSession: (taskRunId) => this.host.killSession(taskRunId),

      updateWorkspaceMode: (tid, mode) =>
        this.host.updateWorkspaceMode(tid, mode),

      onProgress: (step, message) => {
        this.emit(HandoffEvent.Progress, { taskId, step, message });
      },
    };

    const saga = new HandoffToCloudSaga(deps, this.logger);
    const result = await saga.run(input);

    if (!result.success) {
      this.logger.error("Handoff to cloud saga failed", {
        error: result.error,
        failedStep: result.failedStep,
      });
      deps.onProgress("failed", result.error ?? "Handoff to cloud failed");
      const code = extractHandoffErrorCode(result.error);
      return {
        success: false,
        code,
        error:
          code === GITHUB_AUTHORIZATION_REQUIRED_CODE
            ? GITHUB_AUTHORIZATION_REQUIRED_MESSAGE
            : `Handoff to cloud failed at step '${result.failedStep}': ${result.error}`,
      };
    }

    await this.host.cleanupLocalAfterCloudHandoff(
      repoPath,
      input.localGitState?.branch ?? null,
    );

    await this.host.deleteLocalLogCache(runId);

    return {
      success: true,
      logEntryCount: result.data.logEntryCount,
    };
  }
}
