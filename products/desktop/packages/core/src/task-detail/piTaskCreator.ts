import {
  Saga,
  type SagaLogger,
  type TaskCreationInput,
  type TaskCreationOutput,
  type Workspace,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import type { PiRunner } from "../pi-runtime/piRunner";
import type { TaskCreationApiClient } from "./taskCreationApiClient";
import type { ITaskCreationHost } from "./taskCreationHost";
import { resolveTaskRepository } from "./taskRepository";

export interface PiTaskCreatorDeps {
  posthogClient: TaskCreationApiClient;
  host: ITaskCreationHost;
  piRunner: PiRunner;
  onTaskReady?: (output: TaskCreationOutput) => void;
}

export class PiTaskCreator extends Saga<TaskCreationInput, TaskCreationOutput> {
  readonly sagaName = "PiTaskCreator";

  constructor(
    private readonly deps: PiTaskCreatorDeps,
    logger?: SagaLogger,
  ) {
    super(logger);
  }

  protected async execute(
    input: TaskCreationInput,
  ): Promise<TaskCreationOutput> {
    if (input.workspaceMode === "cloud") {
      throw new Error("Pi tasks are only supported in local workspaces");
    }

    const task = await this.createTask(input);
    const repoPath = input.repoPath;
    let workspace: Workspace | null = null;

    if (repoPath) {
      workspace = await this.createWorkspace(task, repoPath, input);
    } else if (input.allowNoRepo) {
      workspace = await this.createScratchWorkspace(task);
    }

    if (!workspace) {
      throw new Error("Pi tasks require a workspace or scratch directory");
    }

    const cwd = workspace.worktreePath ?? workspace.folderPath;
    const additionalDirectories = (input.additionalDirectories ?? []).filter(
      (path) => path && path !== input.repoPath,
    );
    if (additionalDirectories.length > 0) {
      await this.step({
        name: "additional_directories",
        execute: async () => {
          await Promise.all(
            additionalDirectories.map((path) =>
              this.deps.host.addAdditionalDirectory({ taskId: task.id, path }),
            ),
          );
          return { taskId: task.id, paths: additionalDirectories };
        },
        rollback: async ({ taskId, paths }) => {
          await Promise.all(
            paths.map((path) =>
              this.deps.host.removeAdditionalDirectory({ taskId, path }),
            ),
          );
        },
      });
    }

    await this.step({
      name: "pi_session",
      execute: async () => {
        await this.deps.piRunner.create({
          taskId: task.id,
          cwd,
          prompt: input.content ?? "",
          model: input.model,
        });
        return { taskId: task.id };
      },
      rollback: async ({ taskId }) => this.deps.piRunner.stop(taskId),
    });

    this.deps.onTaskReady?.({ task, workspace });
    return { task, workspace };
  }

  private async createTask(input: TaskCreationInput): Promise<Task> {
    const repository = await resolveTaskRepository(
      input,
      this.deps.host,
      this.log,
    );

    return this.step({
      name: "task_creation",
      execute: async () =>
        (await this.deps.posthogClient.createTask({
          description: input.content ?? "",
          repository: repository ?? undefined,
          origin_product: input.signalReportId
            ? "signal_report"
            : "user_created",
          signal_report: input.signalReportId ?? undefined,
          channel: input.channelId ?? undefined,
          runtime: "pi",
        })) as unknown as Task,
      rollback: async (task) => this.deps.posthogClient.deleteTask(task.id),
    });
  }

  private async createWorkspace(
    task: Task,
    repoPath: string,
    input: TaskCreationInput,
  ): Promise<Workspace> {
    const folder = await this.deps.host.getFolders().then(async (folders) => {
      const existing = folders.find((candidate) => candidate.path === repoPath);
      return existing ?? this.deps.host.addFolder({ folderPath: repoPath });
    });
    const workspaceInfo = await this.step({
      name: "workspace_creation",
      execute: () =>
        this.deps.host.createWorkspace({
          taskId: task.id,
          mainRepoPath: repoPath,
          folderId: folder.id,
          folderPath: repoPath,
          mode: input.workspaceMode ?? "local",
          branch: input.branch ?? undefined,
          allowRemoteBranchCheckout: input.allowRemoteBranchCheckout,
          reuseExistingWorktree: input.reuseExistingWorktree,
        }),
      rollback: () =>
        this.deps.host.deleteWorkspace({
          taskId: task.id,
          mainRepoPath: repoPath,
        }),
    });

    const workspaceMode = input.workspaceMode ?? "local";
    const worktree = workspaceInfo.worktree;
    if (workspaceMode === "worktree" && !worktree) {
      throw new Error("Pi worktree creation did not return a worktree");
    }
    if (worktree) {
      return {
        taskId: task.id,
        folderId: folder.id,
        folderPath: repoPath,
        mode: workspaceMode,
        worktreePath: worktree.worktreePath,
        worktreeName: worktree.worktreeName,
        branchName: worktree.branchName,
        baseBranch: worktree.baseBranch,
        linkedBranch: workspaceInfo.linkedBranch,
        createdAt: worktree.createdAt,
      };
    }

    return {
      taskId: task.id,
      folderId: folder.id,
      folderPath: repoPath,
      mode: "local",
      worktreePath: null,
      worktreeName: null,
      branchName: workspaceInfo.branchName,
      baseBranch: input.branch ?? null,
      linkedBranch: workspaceInfo.linkedBranch,
      createdAt: new Date().toISOString(),
    };
  }

  private async createScratchWorkspace(task: Task): Promise<Workspace> {
    const folderPath = await this.deps.host.ensureScratchDir(task.id);
    return {
      taskId: task.id,
      folderId: "",
      folderPath,
      mode: "local",
      worktreePath: null,
      worktreeName: null,
      branchName: null,
      baseBranch: null,
      linkedBranch: null,
      createdAt: new Date().toISOString(),
    };
  }
}
