import { BrowserMcpHandler } from "@posthog/core/task-browser/mcp-handler";
import type { TaskBrowserService } from "@posthog/core/task-browser/taskBrowserService";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserMcpHttpServer } from "./mcp-http-server";

function toolsCall(id: number, args: unknown) {
  return {
    jsonrpc: "2.0",
    id,
    method: "tools/call",
    params: { name: "js", arguments: args },
  };
}

function fakeService() {
  const runCode = vi.fn(async () => ({ ok: true, output: "", images: [] }));
  const service = {
    mcp: new BrowserMcpHandler(runCode),
    forgetTask: vi.fn(),
  };
  return { runCode, service: service as unknown as TaskBrowserService };
}

describe("BrowserMcpHttpServer", () => {
  let server: BrowserMcpHttpServer | null = null;

  afterEach(() => {
    server?.close();
    server = null;
  });

  it("serves each task only with its own token", async () => {
    const { runCode, service } = fakeService();
    server = new BrowserMcpHttpServer(service);
    const [first, second] = await Promise.all([
      server.localConnection("task-1"),
      server.localConnection("task-2"),
    ]);
    expect(second.url).toBe(first.url);
    const post = (token: string | null, body: unknown) =>
      fetch(first.url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });

    expect((await post(null, toolsCall(1, { code: "x" }))).status).toBe(401);
    expect((await post("wrong", toolsCall(1, { code: "x" }))).status).toBe(401);

    const ok = await post(second.token, toolsCall(1, { code: "x" }));
    expect(ok.status).toBe(200);
    expect(runCode).toHaveBeenCalledWith("task-2", "x");

    const notification = await post(first.token, {
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });
    expect(notification.status).toBe(202);

    server.release("task-2");
    expect(service.forgetTask).toHaveBeenCalledWith("task-2");
    expect((await post(second.token, toolsCall(2, { code: "x" }))).status).toBe(
      401,
    );
  });
});
