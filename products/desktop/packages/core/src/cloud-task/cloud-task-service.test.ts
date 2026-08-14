import { describe, expect, it, vi } from "vitest";
import { CloudTaskService } from "./cloud-task";
import { CloudTaskEngine } from "./cloud-task-engine";

function createScopedLog() {
  const scopedLog = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  return { ...scopedLog, scope: vi.fn(() => scopedLog) };
}

describe("CloudTaskService", () => {
  it("preserves the injectable service API as a thin engine wrapper", () => {
    const service = new CloudTaskService(
      {
        authenticatedFetch: vi.fn(),
        getCloudContext: vi.fn(),
      },
      { track: vi.fn() } as never,
      createScopedLog(),
    );

    expect(service).toBeInstanceOf(CloudTaskEngine);
    expect(service.watch).toBeTypeOf("function");
    expect(service.retry).toBeTypeOf("function");
    expect(service.unwatchAll).toBeTypeOf("function");
  });

  it("nudges disconnected watchers to reconnect on power resume", () => {
    let resumeHandler: (() => void) | undefined;
    const disposeResume = vi.fn();
    const powerManager = {
      onResume: vi.fn((handler: () => void) => {
        resumeHandler = handler;
        return disposeResume;
      }),
      preventSleep: vi.fn(() => () => {}),
      hasBuiltInBattery: vi.fn(async () => false),
    };

    const service = new CloudTaskService(
      {
        authenticatedFetch: vi.fn(),
        getCloudContext: vi.fn(),
      },
      { track: vi.fn() } as never,
      createScopedLog(),
      null,
      powerManager,
    );
    const reconnectAll = vi.spyOn(service, "reconnectAllIfDisconnected");

    resumeHandler?.();
    expect(reconnectAll).toHaveBeenCalledTimes(1);

    service.unwatchAll();
    expect(disposeResume).toHaveBeenCalledTimes(1);
  });
});
