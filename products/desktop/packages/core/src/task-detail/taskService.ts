import { CLOUD_USAGE_LIMIT_ERROR_MESSAGE } from "@posthog/api-client/posthog-client";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import type {
  SagaResult,
  TaskCreationInput,
  TaskCreationOutput,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { inject, injectable } from "inversify";
import { PI_RUNNER } from "../pi-runtime/identifiers";
import type { PiRunner } from "../pi-runtime/piRunner";
import { TASK_CREATION_EFFECTS, TASK_CREATION_HOST } from "./identifiers";
import { PiTaskCreator } from "./piTaskCreator";
import type { TaskCreationEffects } from "./taskCreationEffects";
import type { ITaskCreationHost } from "./taskCreationHost";
import { TaskCreationSaga } from "./taskCreationSaga";

export type { TaskCreationInput, TaskCreationOutput };
export { TASK_SERVICE } from "./identifiers";

export type CreateTaskResult = SagaResult<TaskCreationOutput>;

/**
 * True when a failed createTask was blocked by the usage limit. The upgrade modal is
 * already shown in this case, so callers should suppress their own error toast.
 */
export function isUsageLimitResult(result: CreateTaskResult): boolean {
  return (
    !result.success &&
    (result.failedStep === "usage_limit" ||
      result.error === CLOUD_USAGE_LIMIT_ERROR_MESSAGE)
  );
}

@injectable()
export class TaskService {
  constructor(
    @inject(TASK_CREATION_HOST)
    private readonly host: ITaskCreationHost,
    @inject(SESSION_SERVICE)
    private readonly sessionService: SessionService,
    @inject(TASK_CREATION_EFFECTS)
    private readonly effects: TaskCreationEffects,
    @inject(PI_RUNNER)
    private readonly piRunner: PiRunner,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("task-service");
  }

  private readonly log: ReturnType<RootLogger["scope"]>;

  public async createTask(
    input: TaskCreationInput,
    onTaskReady?: (output: TaskCreationOutput) => void,
    options?: { skipCloudUsagePreflight?: boolean },
  ): Promise<CreateTaskResult> {
    this.log.info("Creating task", {
      workspaceMode: input.workspaceMode,
      hasContent: !!input.content,
      hasRepo: !!input.repository,
    });

    // Promptless flows (imported Claude Code sessions, worktree adoption)
    // synthesize a taskDescription instead of typed content; either one names
    // the task, so either satisfies validation.
    const hasDescription =
      !!input.content?.trim() || !!input.taskDescription?.trim();
    if (!hasDescription) {
      return {
        success: false,
        error: "Task description cannot be empty",
        failedStep: "validation",
      };
    }

    const posthogClient = await this.host.getAuthenticatedClient();
    if (!posthogClient) {
      return {
        success: false,
        error: "Not authenticated",
        failedStep: "validation",
      };
    }

    // Backstop for callers that bypass useTaskCreation (e.g. inbox); the helper shows the modal.
    // Callers that already pre-flighted pass skipCloudUsagePreflight to avoid a second fetch.
    if (!options?.skipCloudUsagePreflight && input.workspaceMode === "cloud") {
      try {
        await this.host.assertCloudUsageAvailable();
      } catch (error) {
        if (
          error instanceof Error &&
          error.message === CLOUD_USAGE_LIMIT_ERROR_MESSAGE
        ) {
          return {
            success: false,
            error: CLOUD_USAGE_LIMIT_ERROR_MESSAGE,
            failedStep: "usage_limit",
          };
        }
        throw error;
      }
    }

    let result: CreateTaskResult;
    if (input.runtime === "pi") {
      const creator = new PiTaskCreator(
        {
          posthogClient,
          host: this.host,
          piRunner: this.piRunner,
          onTaskReady,
        },
        this.log,
      );
      result = await creator.run(input);
    } else {
      const creator = new TaskCreationSaga(
        {
          posthogClient,
          host: this.host,
          sessionService: this.sessionService,
          track: (event, props) => this.host.track(event, props),
          onTaskReady,
        },
        this.log,
      );
      result = await creator.run(input);
    }

    if (result.success) {
      this.effects.onWorkspaceCreated(result.data);
      this.effects.onCreateSuccess(result.data, input);
    }

    return result;
  }

  public async openTask(
    taskId: string,
    taskRunId?: string,
  ): Promise<CreateTaskResult> {
    this.log.info("Opening existing task", { taskId, taskRunId });

    const posthogClient = await this.host.getAuthenticatedClient();
    if (!posthogClient) {
      return {
        success: false,
        error: "Not authenticated",
        failedStep: "validation",
      };
    }

    let task: Task;
    try {
      task = await posthogClient.getTask(taskId);
      if (taskRunId) {
        this.log.info("Fetching specific task run", { taskId, taskRunId });
        task.latest_run = await posthogClient.getTaskRun(taskId, taskRunId);
      }
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Failed to fetch task",
        failedStep: "fetch_task",
      };
    }

    const runtime = task.runtime === "pi" ? "pi" : "acp";
    const existingWorkspace = await this.host.getWorkspace(taskId);
    if (existingWorkspace) {
      this.log.info("Workspace already exists, fetching task only", { taskId });
      try {
        if (runtime === "pi") {
          await this.piRunner.resume({
            taskId,
            cwd: existingWorkspace.worktreePath ?? existingWorkspace.folderPath,
          });
        }

        return {
          success: true,
          data: { task, workspace: existingWorkspace },
        };
      } catch (error) {
        return {
          success: false,
          error:
            error instanceof Error ? error.message : "Failed to resume task",
          failedStep: runtime === "pi" ? "pi_session" : "fetch_task",
        };
      }
    }

    if (runtime === "pi") {
      try {
        const cwd = await this.host.ensureScratchDir(taskId);
        await this.piRunner.resume({ taskId, cwd });
        return {
          success: true,
          data: { task, workspace: null },
        };
      } catch (error) {
        return {
          success: false,
          error:
            error instanceof Error
              ? error.message
              : "Failed to resume Pi session",
          failedStep: "pi_session",
        };
      }
    }

    const saga = new TaskCreationSaga(
      {
        posthogClient,
        host: this.host,
        sessionService: this.sessionService,
        track: (event, props) => this.host.track(event, props),
      },
      this.log,
    );
    const result = await saga.run({ taskId });

    if (result.success) {
      this.effects.onWorkspaceCreated(result.data);
      this.effects.onCreateSuccess(result.data);

      if (taskRunId && result.data.task) {
        try {
          this.log.info("Fetching specific task run for new workspace", {
            taskId,
            taskRunId,
          });
          const run = await posthogClient.getTaskRun(taskId, taskRunId);
          result.data.task.latest_run = run;
        } catch (error) {
          this.log.warn("Failed to fetch specific task run, using latest", {
            taskId,
            taskRunId,
            error,
          });
        }
      }
    }

    return result;
  }
}
