import { describe, expect, it } from "vitest";
import { McpManager } from "./mcp-manager";

function itemParams(overrides?: Record<string, unknown>) {
  return {
    item: {
      type: "mcpToolCall",
      id: "m1",
      server: "posthog",
      tool: "exec",
      arguments: { command: "call execute-sql {}" },
      ...overrides,
    },
  };
}

describe("McpManager", () => {
  it("captures an mcpToolCall and resolves it by item id and by server", () => {
    const mcp = new McpManager();
    mcp.capture(itemParams());

    expect(mcp.byItemId("m1")).toEqual({
      server: "posthog",
      tool: "exec",
      args: { command: "call execute-sql {}" },
    });
    expect(mcp.byServer("posthog")?.tool).toBe("exec");
    expect(mcp.byServer("github")).toBeUndefined();
    expect(mcp.byItemId(undefined)).toBeUndefined();
  });

  it("ignores non-mcpToolCall and incomplete items", () => {
    const mcp = new McpManager();
    mcp.capture({ item: { type: "commandExecution", id: "c1" } });
    mcp.capture(itemParams({ server: undefined }));
    mcp.capture(itemParams({ id: undefined }));
    mcp.capture(undefined);

    expect(mcp.byItemId("m1")).toBeUndefined();
    expect(mcp.byItemId("c1")).toBeUndefined();
    expect(mcp.byServer("posthog")).toBeUndefined();
  });

  it("tracks the latest in-flight call per server for elicitations", () => {
    const mcp = new McpManager();
    mcp.capture(itemParams());
    mcp.capture(itemParams({ id: "m2", server: "github", tool: "search" }));

    expect(mcp.byServer("github")?.tool).toBe("search");
    // The posthog call is no longer the latest, so an elicitation cannot map to it.
    expect(mcp.byServer("posthog")).toBeUndefined();
    expect(mcp.byItemId("m1")?.server).toBe("posthog");
  });

  it("evicts a completed call so lookups no longer resolve and the map cannot grow unbounded", () => {
    const mcp = new McpManager();
    mcp.capture(itemParams());
    mcp.release(itemParams());

    expect(mcp.byItemId("m1")).toBeUndefined();
    expect(mcp.byServer("posthog")).toBeUndefined();
  });

  it("keeps the latest pointer when an older call completes", () => {
    const mcp = new McpManager();
    mcp.capture(itemParams());
    mcp.capture(itemParams({ id: "m2", tool: "query" }));
    mcp.release(itemParams());

    expect(mcp.byItemId("m1")).toBeUndefined();
    expect(mcp.byServer("posthog")?.tool).toBe("query");
  });
});
