import type { SessionService } from "@posthog/core/sessions/sessionService";
import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it, vi } from "vitest";
import type { PiRunner } from "../pi-runtime/piRunner";
import type { TaskCreationEffects } from "./taskCreationEffects";
import type { ITaskCreationHost } from "./taskCreationHost";
import { buildWorktreeAdoptionInput } from "./taskInput";
import { TaskService } from "./taskService";

const scopedLog = {
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
};
const rootLogger = {
  ...scopedLog,
  scope: () => scopedLog,
} as unknown as RootLogger;

function makeService(): TaskService {
  const host = {
    // The API client's createTask rejects so tests can observe that an input
    // made it past validation (failedStep lands on task_creation, not
    // validation) without faking the whole saga.
    getAuthenticatedClient: vi.fn(async () => ({
      createTask: vi.fn().mockRejectedValue(new Error("api down")),
      deleteTask: vi.fn(),
      getTask: vi.fn(),
      createTaskRun: vi.fn(),
      startTaskRun: vi.fn(),
      sendRunCommand: vi.fn(),
      updateTask: vi.fn(),
    })),
    detectRepo: vi.fn(async () => null),
    getFolders: vi.fn(async () => []),
    addFolder: vi.fn(async () => ({ id: "folder-1", path: "/repo" })),
    track: vi.fn(),
  } as unknown as ITaskCreationHost;
  const sessionService = {
    markTaskCreationInFlight: vi.fn(),
    connectToTask: vi.fn(),
    disconnectFromTask: vi.fn(),
  } as unknown as SessionService;
  const effects = {
    onWorkspaceCreated: vi.fn(),
    onCreateSuccess: vi.fn(),
  } as unknown as TaskCreationEffects;
  const piRunner = {
    create: vi.fn(),
    resume: vi.fn(),
    stop: vi.fn(),
  } as unknown as PiRunner;
  return new TaskService(host, sessionService, effects, piRunner, rootLogger);
}

describe("TaskService.openTask", () => {
  it("opens a completed cloud Pi run without resuming it", async () => {
    const completedRun = {
      id: "run-1",
      environment: "cloud",
      status: "completed",
    };
    const api = {
      getTask: vi.fn(async () => ({
        id: "task-1",
        runtime: "pi",
        latest_run: completedRun,
      })),
      getTaskRun: vi.fn(async () => completedRun),
      resumeRunInCloud: vi.fn(),
    };
    const workspace = { folderPath: "/repo" };
    const host = {
      getAuthenticatedClient: vi.fn(async () => api),
      getWorkspace: vi.fn(async () => workspace),
    } as unknown as ITaskCreationHost;
    const piRunner = {
      create: vi.fn(),
      resume: vi.fn(),
      stop: vi.fn(),
    } as unknown as PiRunner;
    const service = new TaskService(
      host,
      {} as SessionService,
      {} as TaskCreationEffects,
      piRunner,
      rootLogger,
    );

    const result = await service.openTask("task-1", "run-1");

    expect(result.success).toBe(true);
    expect(api.resumeRunInCloud).not.toHaveBeenCalled();
    expect(piRunner.resume).not.toHaveBeenCalled();
    if (result.success) {
      expect(result.data.task.latest_run).toBe(completedRun);
      expect(result.data.workspace).toBe(workspace);
    }
  });
});

describe("TaskService.resumeCloudPiRun", () => {
  it("publishes the resumed run to host state", async () => {
    const run = {
      id: "run-2",
      task_id: "task-1",
      environment: "cloud",
      status: "queued",
    };
    const api = {
      resumeRunInCloud: vi.fn(async () => run),
    };
    const effects = {
      onRunResumed: vi.fn(),
    } as unknown as TaskCreationEffects;
    const service = new TaskService(
      {
        getAuthenticatedClient: vi.fn(async () => api),
      } as unknown as ITaskCreationHost,
      {} as SessionService,
      effects,
      {} as PiRunner,
      rootLogger,
    );

    await expect(service.resumeCloudPiRun("task-1", "run-1")).resolves.toBe(
      run,
    );
    expect(effects.onRunResumed).toHaveBeenCalledWith("task-1", run);
  });
});

describe("TaskService.createTask validation", () => {
  it("rejects an input with neither content nor a taskDescription", async () => {
    const result = await makeService().createTask({
      content: "   ",
      repoPath: "/repo",
      workspaceMode: "worktree",
    });

    expect(result.success).toBe(false);
    if (result.success) throw new Error("expected validation failure");
    expect(result.failedStep).toBe("validation");
  });

  it("accepts a promptless worktree-adoption input", async () => {
    const result = await makeService().createTask(
      buildWorktreeAdoptionInput({
        repoPath: "/repo",
        branch: "feature/orphan",
      }),
    );

    // The stubbed API call fails, proving the input got past validation.
    expect(result.success).toBe(false);
    if (result.success) throw new Error("expected task_creation failure");
    expect(result.failedStep).toBe("task_creation");
  });
});
