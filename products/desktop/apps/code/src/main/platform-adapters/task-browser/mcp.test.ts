import { afterEach, describe, expect, it, vi } from "vitest";
import { BrowserMcpHandler, BrowserMcpHttpServer } from "./mcp";
import type { BrowserRunner } from "./runner";

function runner() {
  return {
    run: vi.fn(async () => ({
      ok: true,
      output: "Clicked Save",
      images: [{ data: "aW1n", mimeType: "image/jpeg" }],
    })),
  };
}

function toolsCall(id: number, args: unknown) {
  return {
    jsonrpc: "2.0",
    id,
    method: "tools/call",
    params: { name: "js", arguments: args },
  };
}

describe("browser MCP", () => {
  let server: BrowserMcpHttpServer | null = null;

  afterEach(() => {
    server?.close();
    server = null;
  });

  it("runs the js tool for the task and returns its text and screenshots", async () => {
    const fake = runner();
    const handler = new BrowserMcpHandler(fake as unknown as BrowserRunner);

    const response = await handler.handle(
      "task-1",
      toolsCall(3, { code: "return 1" }),
    );

    expect(fake.run).toHaveBeenCalledWith("task-1", "return 1");
    expect(response).toEqual({
      jsonrpc: "2.0",
      id: 3,
      result: {
        isError: false,
        content: [
          { type: "text", text: "Clicked Save" },
          { type: "image", data: "aW1n", mimeType: "image/jpeg" },
        ],
      },
    });
  });

  it.each([
    ["another tool", { ...toolsCall(4, {}), params: { name: "eval" } }],
    ["no code", toolsCall(4, {})],
  ])("rejects a call with %s without running code", async (_name, payload) => {
    const fake = runner();
    const handler = new BrowserMcpHandler(fake as unknown as BrowserRunner);

    const response = await handler.handle("task-1", payload);

    expect(response?.error?.code).toBe(-32602);
    expect(fake.run).not.toHaveBeenCalled();
  });

  it("serves each task only with its own token", async () => {
    const fake = runner();
    server = new BrowserMcpHttpServer(
      new BrowserMcpHandler(fake as unknown as BrowserRunner),
    );
    const first = await server.connectionFor("task-1");
    const second = await server.connectionFor("task-2");
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
    expect(fake.run).toHaveBeenCalledWith("task-2", "x");

    const notification = await post(first.token, {
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });
    expect(notification.status).toBe(202);

    server.revoke("task-2");
    expect((await post(second.token, toolsCall(2, { code: "x" }))).status).toBe(
      401,
    );
  });
});
