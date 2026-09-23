import { PiRuntime } from "@posthog/agent/pi/runtime";
import type { PiRpcClientFactory } from "@posthog/workspace-server/services/pi-session/identifiers";
import { describe, expect, it, vi } from "vitest";
import { DesktopPiRuntimeFactory } from "./desktop-pi-runtime-factory";

describe("DesktopPiRuntimeFactory", () => {
  it("wraps the host-authenticated RPC client", async () => {
    const client = { onEvent: vi.fn() };
    const clientFactory = {
      create: vi.fn(async () => client),
    } as unknown as PiRpcClientFactory;
    const factory = new DesktopPiRuntimeFactory(clientFactory);

    const runtime = await factory.create({
      taskContext: { taskId: "task-1", cwd: "/workspace" },
    });

    expect(runtime).toBeInstanceOf(PiRuntime);
    expect(runtime.client).toBe(client);
    expect(clientFactory.create).toHaveBeenCalledWith({
      taskContext: { taskId: "task-1", cwd: "/workspace" },
    });
  });
});
