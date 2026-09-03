import type { ReportModelResolver } from "@posthog/core/inbox/identifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import type { TaskService } from "@posthog/core/task-detail/taskService";
import type { RootLogger } from "@posthog/di/logger";
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
    {
      scope: () => ({ warn: vi.fn(), error: vi.fn() }),
    } as unknown as RootLogger,
  );
  return { service, createTask, resolveDefaultModel, generateCanvasName };
}

function makeGateway() {
  return {
    fileTask: vi.fn(async (_channelId: string, _taskId: string) => {}),
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
    // No caller pick: prefer Sonnet 5 over the gateway's default, validated
    // by the resolver against the gateway's model list.
    expect(resolveDefaultModel).toHaveBeenCalledWith(
      "https://us.posthog.com",
      "claude",
      "claude-sonnet-5",
    );
    const [taskInput] = createTask.mock.calls[0];
    expect(taskInput.content).toContain("`building-canvases` skill");
    expect(taskInput.content).toContain('canvas id: "dash-1"');
    expect(taskInput).toMatchObject({
      executionMode: "bypassPermissions",
      workspaceMode: "cloud",
      adapter: "claude",
      model: "model-1",
      allowNoRepo: true,
    });
    expect(gateway.fileTask).toHaveBeenCalledWith("chan-1", "task-1");
    expect(gateway.setGenerationTask).toHaveBeenCalledWith("dash-1", "task-1");
  });

  it("scopes a placement fill to its tile: skill routing, no canvas-level generation state", async () => {
    const { service, createTask, generateCanvasName } = makeDeps();
    const gateway = makeGateway();

    const result = await service.generateCanvas(
      input({
        name: "Untitled canvas",
        placement: { placementId: "p-1", w: 2, h: 1 },
      }),
      gateway,
    );

    expect(result).toEqual({ ok: true, taskId: "task-1" });
    const [taskInput] = createTask.mock.calls[0];
    expect(taskInput.content).toContain("`composing-grid-canvases` skill");
    expect(taskInput.content).toContain('placement id: "p-1"');
    // Named after the widget, not the canvas — every fill on the same canvas
    // would otherwise share one "Generate canvas ..." title.
    expect(taskInput.taskDescription).toBe(
      "Generate widget: build a signups chart",
    );
    expect(gateway.fileTask).toHaveBeenCalledWith("chan-1", "task-1");
    // The placement row carries the task id; the canvas itself is not
    // generating and must not be renamed from one widget's prompt.
    expect(gateway.setGenerationTask).not.toHaveBeenCalled();
    expect(generateCanvasName).not.toHaveBeenCalled();
  });

  it("routes a whole-grid-canvas run to the grid skill and records it on the canvas", async () => {
    const { service, createTask } = makeDeps();
    const gateway = makeGateway();

    const result = await service.generateCanvas(
      input({
        name: "Home",
        instruction: "fix the weather widget's query",
        canvasKind: "grid",
      }),
      gateway,
    );

    expect(result).toEqual({ ok: true, taskId: "task-1" });
    const [taskInput] = createTask.mock.calls[0];
    expect(taskInput.content).toContain("`composing-grid-canvases` skill");
    expect(taskInput.content).toContain("WHOLE grid canvas");
    expect(taskInput.taskDescription).toBe(
      'Update canvas "Home": fix the weather widget\'s query',
    );
    // The whole-canvas conversation is recorded so it can be reopened.
    expect(gateway.setGenerationTask).toHaveBeenCalledWith("dash-1", "task-1");
  });

  // The effort default must follow the model: "high" sent alongside a
  // fallback model that doesn't support it makes the task API reject the run.
  it.each([
    ["claude-sonnet-5", "high"],
    ["model-1", undefined],
  ])(
    "defaults reasoning effort only when the preferred model resolved (%s)",
    async (resolved, expectedEffort) => {
      const { service, createTask } = makeDeps({
        resolveDefaultModel: vi.fn().mockResolvedValue(resolved),
      });

      await service.generateCanvas(input(), makeGateway());

      expect(createTask.mock.calls[0][0].reasoningLevel).toBe(expectedEffort);
    },
  );

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
