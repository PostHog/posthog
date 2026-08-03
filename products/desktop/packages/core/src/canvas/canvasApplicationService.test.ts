import type { ReportModelResolver } from "@posthog/core/inbox/identifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import type { TaskService } from "@posthog/core/task-detail/taskService";
import { describe, expect, it, vi } from "vitest";
import {
  CanvasApplicationService,
  type CanvasGenerationGateway,
  type GenerateCanvasInput,
} from "./canvasApplicationService";

const TASK = { id: "task-1", title: "Generate canvas" };

function makeDeps(overrides?: {
  createTask?: ReturnType<typeof vi.fn>;
  resolveDefaultModel?: ReturnType<typeof vi.fn>;
  generateCanvasName?: ReturnType<typeof vi.fn>;
}) {
  const createTask =
    overrides?.createTask ??
    vi.fn().mockResolvedValue({ success: true, data: { task: TASK } });
  const resolveDefaultModel =
    overrides?.resolveDefaultModel ?? vi.fn().mockResolvedValue("model-1");
  const generateCanvasName =
    overrides?.generateCanvasName ?? vi.fn().mockResolvedValue(null);

  const service = new CanvasApplicationService(
    { createTask } as unknown as TaskService,
    { resolveDefaultModel } as unknown as ReportModelResolver,
    { generateCanvasName } as unknown as TitleGeneratorService,
  );
  return { service, createTask, resolveDefaultModel, generateCanvasName };
}

function makeGateway() {
  return {
    fileTask: vi.fn(
      async (_channelId: string, _taskId: string, _title: string) => {},
    ),
    setGenerationTask: vi.fn(
      async (_dashboardId: string, _taskId: string) => {},
    ),
    renameCanvas: vi.fn(async (_dashboardId: string, _title: string) => {}),
    onAutoNamed: vi.fn((_taskId: string, _title: string) => {}),
  } satisfies CanvasGenerationGateway;
}

function input(
  overrides: Partial<GenerateCanvasInput> = {},
): GenerateCanvasInput {
  return {
    dashboardId: "dash-1",
    name: "Signups",
    instruction: "build a signups chart",
    isEdit: false,
    channelId: "chan-1",
    channelName: "growth",
    cloudRegion: "us",
    ...overrides,
  };
}

describe("CanvasApplicationService", () => {
  it("starts a repo-less cloud task routed into the canvas skills and records it on the canvas", async () => {
    const { service, createTask, resolveDefaultModel } = makeDeps();
    const gateway = makeGateway();

    const result = await service.generateCanvas(input(), gateway);

    expect(result).toEqual({ ok: true, taskId: "task-1" });
    expect(resolveDefaultModel).toHaveBeenCalledWith(
      "https://us.posthog.com",
      "claude",
      undefined,
    );
    const [taskInput] = createTask.mock.calls[0];
    expect(taskInput.content).toContain("`building-canvases` skill");
    expect(taskInput.content).toContain('canvas id: "dash-1"');
    expect(taskInput).toMatchObject({
      executionMode: "auto",
      workspaceMode: "cloud",
      adapter: "claude",
      model: "model-1",
      allowNoRepo: true,
    });
    expect(gateway.fileTask).toHaveBeenCalledWith(
      "chan-1",
      "task-1",
      TASK.title,
    );
    expect(gateway.setGenerationTask).toHaveBeenCalledWith("dash-1", "task-1");
  });

  it.each([
    ["no signed-in region", input({ cloudRegion: null })],
    ["resolver returns nothing", input(), vi.fn().mockResolvedValue(undefined)],
  ])(
    "refuses a cloud run without a resolvable model (%s)",
    async (_name, generateInput, resolveDefaultModel?) => {
      const { service, createTask } = makeDeps({ resolveDefaultModel });
      const result = await service.generateCanvas(generateInput, makeGateway());

      expect(result).toEqual({ ok: false, reason: "no-model" });
      expect(createTask).not.toHaveBeenCalled();
    },
  );

  it("skips model resolution for local runs", async () => {
    const { service, resolveDefaultModel, createTask } = makeDeps();

    const result = await service.generateCanvas(
      input({ workspaceMode: "local", cloudRegion: null }),
      makeGateway(),
    );

    expect(result).toEqual({ ok: true, taskId: "task-1" });
    expect(resolveDefaultModel).not.toHaveBeenCalled();
    expect(createTask.mock.calls[0][0].workspaceMode).toBe("local");
  });

  it("surfaces a failed task creation without touching the canvas", async () => {
    const { service } = makeDeps({
      createTask: vi.fn().mockResolvedValue({ success: false, error: "boom" }),
    });
    const gateway = makeGateway();

    const result = await service.generateCanvas(input(), gateway);

    expect(result).toEqual({
      ok: false,
      reason: "create-failed",
      error: "boom",
    });
    expect(gateway.fileTask).not.toHaveBeenCalled();
    expect(gateway.setGenerationTask).not.toHaveBeenCalled();
  });

  it("auto-names a placeholder canvas after the run starts", async () => {
    const { service, generateCanvasName } = makeDeps({
      generateCanvasName: vi.fn().mockResolvedValue("  Signups overview "),
    });
    const gateway = makeGateway();

    await service.generateCanvas(input({ name: "Untitled canvas" }), gateway);

    await vi.waitFor(() => {
      expect(gateway.renameCanvas).toHaveBeenCalledWith(
        "dash-1",
        "Signups overview",
      );
    });
    expect(generateCanvasName).toHaveBeenCalledWith("build a signups chart");
    expect(gateway.onAutoNamed).toHaveBeenCalledWith(
      "task-1",
      "Signups overview",
    );
  });

  it("never renames a canvas the user already titled", async () => {
    const { service, generateCanvasName } = makeDeps();
    const gateway = makeGateway();

    await service.generateCanvas(input({ name: "Signups" }), gateway);

    expect(generateCanvasName).not.toHaveBeenCalled();
    expect(gateway.renameCanvas).not.toHaveBeenCalled();
  });

  it("still starts the task when recording the generation task fails", async () => {
    const { service } = makeDeps();
    const gateway = makeGateway();
    gateway.setGenerationTask.mockRejectedValue(new Error("offline"));

    const result = await service.generateCanvas(input(), gateway);

    expect(result).toEqual({ ok: true, taskId: "task-1" });
  });
});
