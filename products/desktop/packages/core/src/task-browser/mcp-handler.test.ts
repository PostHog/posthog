import { describe, expect, it, vi } from "vitest";
import { BrowserMcpHandler } from "./mcp-handler";

function runCode() {
  return vi.fn(async () => ({
    ok: true,
    output: "Clicked Save",
    images: [{ data: "aW1n", mimeType: "image/jpeg" as const }],
  }));
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
  it("runs the js tool for the task and returns its text and screenshots", async () => {
    const fake = runCode();
    const handler = new BrowserMcpHandler(fake);

    const response = await handler.handle(
      "task-1",
      toolsCall(3, { code: "return 1" }),
    );

    expect(fake).toHaveBeenCalledWith("task-1", "return 1");
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
    const fake = runCode();
    const handler = new BrowserMcpHandler(fake);

    const response = await handler.handle("task-1", payload);

    expect(response?.error?.code).toBe(-32602);
    expect(fake).not.toHaveBeenCalled();
  });
});
