import { describe, expect, it, vi } from "vitest";
import { ProvisioningEvent, ProvisioningService } from "./provisioning";

describe("ProvisioningService", () => {
  it("emits an Output event carrying the task id and data", () => {
    const service = new ProvisioningService();
    const listener = vi.fn();
    service.on(ProvisioningEvent.Output, listener);

    service.emitOutput("task-1", "hello world");

    expect(listener).toHaveBeenCalledWith({
      taskId: "task-1",
      data: "hello world",
    });
  });

  it("emits one event per emitOutput call", () => {
    const service = new ProvisioningService();
    const listener = vi.fn();
    service.on(ProvisioningEvent.Output, listener);

    service.emitOutput("task-1", "a");
    service.emitOutput("task-1", "b");

    expect(listener).toHaveBeenCalledTimes(2);
  });
});
