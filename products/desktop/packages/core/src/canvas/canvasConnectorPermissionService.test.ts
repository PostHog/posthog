import { describe, expect, it } from "vitest";
import { CanvasConnectorPermissionService } from "./canvasConnectorPermissionService";

describe("canvas connector permissions", () => {
  it("denies pending requests when authentication-scoped queries are canceled", async () => {
    const service = new CanvasConnectorPermissionService();
    const controller = new AbortController();
    const input = {
      provider: "github",
      tool: "list_pull_requests",
      reason: "canvas" as const,
    };
    const pending = service.request(Symbol(), input, controller.signal);
    controller.abort();
    await expect(pending).resolves.toBe(false);
    expect(service.store.getState().pending).toHaveLength(0);
    await expect(
      service.request(Symbol(), input, controller.signal),
    ).resolves.toBe(false);
    expect(service.store.getState().pending).toHaveLength(0);
  });
  it("queues requests and cancels only the closed canvas", async () => {
    const service = new CanvasConnectorPermissionService();
    const firstOwner = Symbol("first");
    const secondOwner = Symbol("second");
    const input = {
      provider: "mcp:example.com",
      tool: "list_events",
      reason: "tool" as const,
    };
    const first = service.request(firstOwner, input);
    const second = service.request(secondOwner, input);
    const third = service.request(firstOwner, input);
    const staleRequest = service.store.getState().pending[0];
    service.cancel(firstOwner);
    service.respond(staleRequest, true);
    await expect(first).resolves.toBe(false);
    await expect(third).resolves.toBe(false);
    expect(service.store.getState().pending).toHaveLength(1);
    service.respond(service.store.getState().pending[0], true);
    await expect(second).resolves.toBe(true);
    expect(service.store.getState().pending).toHaveLength(0);
  });
});
