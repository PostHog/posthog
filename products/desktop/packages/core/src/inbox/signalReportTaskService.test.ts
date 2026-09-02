import { describe, expect, it, vi } from "vitest";
import type { TaskService } from "../task-detail/taskService";
import type { ReportModelResolver } from "./identifiers";
import {
  type CreateSignalReportTaskInput,
  SignalReportTaskService,
} from "./signalReportTaskService";

function makeInput(
  overrides: Partial<CreateSignalReportTaskInput> = {},
): CreateSignalReportTaskInput {
  return {
    kind: "discuss",
    reportId: "r1",
    reportTitle: "Title",
    cloudRepository: "owner/repo",
    githubUserIntegrationId: "ghu_1",
    cloudRegion: "us",
    adapter: "claude",
    modelOverride: "claude-sonnet",
    isDevBuild: false,
    ...overrides,
  };
}

function makeService(
  taskOverrides: Partial<TaskService> = {},
  resolver: Partial<ReportModelResolver> = {},
) {
  const createTask = vi
    .fn()
    .mockResolvedValue({ success: true, data: { task: {} } });
  const taskService = {
    createTask,
    ...taskOverrides,
  } as unknown as TaskService;
  const modelResolver = {
    resolveDefaultModel: vi.fn().mockResolvedValue("default-model"),
    ...resolver,
  } as ReportModelResolver;
  return {
    service: new SignalReportTaskService(taskService, modelResolver),
    createTask,
    modelResolver,
  };
}

describe("SignalReportTaskService", () => {
  it("aborts without creating a task when no repository", async () => {
    const { service, createTask } = makeService();
    const result = await service.createSignalReportTask(
      makeInput({ cloudRepository: null }),
      vi.fn(),
    );
    expect(result.status).toBe("missing-repository");
    expect(createTask).not.toHaveBeenCalled();
  });

  it("aborts when no integration id", async () => {
    const { service } = makeService();
    const result = await service.createSignalReportTask(
      makeInput({ githubUserIntegrationId: null }),
      vi.fn(),
    );
    expect(result.status).toBe("missing-integration");
  });

  it("falls back to the model resolver when no override", async () => {
    const { service, createTask, modelResolver } = makeService();
    const result = await service.createSignalReportTask(
      makeInput({ modelOverride: null }),
      vi.fn(),
    );
    expect(modelResolver.resolveDefaultModel).toHaveBeenCalled();
    expect(createTask).toHaveBeenCalledTimes(1);
    expect(result.status).toBe("created");
  });

  it("forwards the override to the resolver as a preference, not a hard selection", async () => {
    // The resolver validates the override against the gateway's available
    // models, so it must receive it rather than the service short-circuiting.
    const { service, modelResolver } = makeService();
    await service.createSignalReportTask(
      makeInput({ modelOverride: "claude-sonnet" }),
      vi.fn(),
    );
    expect(modelResolver.resolveDefaultModel).toHaveBeenCalledWith(
      expect.any(String),
      "claude",
      "claude-sonnet",
    );
  });

  it("aborts with missing-model when no model can be resolved", async () => {
    const { service, createTask } = makeService(
      {},
      { resolveDefaultModel: vi.fn().mockResolvedValue(undefined) },
    );
    const result = await service.createSignalReportTask(
      makeInput({ modelOverride: null }),
      vi.fn(),
    );
    expect(result.status).toBe("missing-model");
    expect(createTask).not.toHaveBeenCalled();
  });

  it("falls back to the explicit override when the resolver fails transiently", async () => {
    // A transient resolver failure returns undefined; a caller-supplied override
    // is already a concrete model, so the run should use it rather than block.
    const { service, createTask } = makeService(
      {},
      { resolveDefaultModel: vi.fn().mockResolvedValue(undefined) },
    );
    const result = await service.createSignalReportTask(
      makeInput({ modelOverride: "claude-sonnet" }),
      vi.fn(),
    );
    expect(result.status).toBe("created");
    expect(createTask).toHaveBeenCalledTimes(1);
    expect(createTask.mock.calls[0][0].model).toBe("claude-sonnet");
  });

  it("returns create-failed when the saga fails", async () => {
    const { service } = makeService({
      createTask: vi
        .fn()
        .mockResolvedValue({ success: false, error: "nope", failedStep: "x" }),
    });
    const result = await service.createSignalReportTask(makeInput(), vi.fn());
    expect(result.status).toBe("create-failed");
    if (result.status === "create-failed") {
      expect(result.error).toBe("nope");
    }
  });

  it("returns errored when createTask throws", async () => {
    const { service } = makeService({
      createTask: vi.fn().mockRejectedValue(new Error("boom")),
    });
    const result = await service.createSignalReportTask(makeInput(), vi.fn());
    expect(result.status).toBe("errored");
  });
});
