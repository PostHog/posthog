import { describe, expect, it, vi } from "vitest";
import { CloudTaskService } from "./cloud-task";
import { CloudTaskEngine } from "./cloud-task-engine";

describe("CloudTaskService", () => {
  it("preserves the service API and ignores subscription designation without a token store", async () => {
    const scopedLog = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };
    const service = new CloudTaskService(
      {
        authenticatedFetch: vi.fn(),
        getCloudContext: vi.fn(),
      },
      { track: vi.fn() } as never,
      { ...scopedLog, scope: vi.fn(() => scopedLog) },
    );

    expect(service).toBeInstanceOf(CloudTaskEngine);
    expect(service.watch).toBeTypeOf("function");
    expect(service.retry).toBeTypeOf("function");
    expect(service.unwatchAll).toBeTypeOf("function");
    await expect(
      service.designateClaudeSubscription({ taskId: "task-1", runId: "run-1" }),
    ).resolves.toBeUndefined();
  });
});
