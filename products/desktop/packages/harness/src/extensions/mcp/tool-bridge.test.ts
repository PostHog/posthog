import type { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { describe, expect, it, vi } from "vitest";
import type { McpSettings } from "./config";
import { McpError } from "./errors";
import type { ToolBridgeHost } from "./tool-bridge";
import {
  type BridgedContent,
  buildToolName,
  convertMcpContent,
  listAllTools,
  ToolBridge,
  truncateBridgedContent,
} from "./tool-bridge";

const settings: McpSettings = {
  toolPrefix: "mcp",
  requestTimeoutMs: 5_000,
  maxRetries: 3,
  searchResultLimit: 15,
};

interface RegisteredTool {
  name: string;
  label: string;
  description: string;
  parameters: unknown;
  renderCall?: unknown;
  execute: (
    toolCallId: string,
    params: unknown,
    signal?: AbortSignal,
  ) => Promise<{ content: Array<{ type: string; text?: string }> }>;
}

function fakeHost(initialActive: string[] = ["read", "bash"]) {
  const registered = new Map<string, RegisteredTool>();
  let active = [...initialActive];
  const host = {
    registerTool: (tool: unknown) => {
      const t = tool as RegisteredTool;
      // Matches real pi (`agent-session.js` `_refreshToolRegistry`): a
      // brand-new tool name is auto-activated the instant it's registered.
      // ToolBridge.activateServer() must always correct for this (never
      // early-return) even when a server has nothing to explicitly add.
      const isNew = !registered.has(t.name);
      registered.set(t.name, t);
      if (isNew && !active.includes(t.name)) {
        active = [...active, t.name];
      }
    },
    getActiveTools: () => [...active],
    setActiveTools: (names: string[]) => {
      active = [...names];
    },
  } as unknown as ToolBridgeHost;
  return { host, registered, getActive: () => active };
}

function fakeClient(handlers: {
  tools?: Array<Record<string, unknown>>;
  onCall?: (params: Record<string, unknown>) => unknown;
}): Client {
  return {
    request: vi.fn(
      async (req: { method: string; params: Record<string, unknown> }) => {
        if (req.method === "tools/list") {
          return { tools: handlers.tools ?? [] };
        }
        if (req.method === "tools/call") {
          return handlers.onCall?.(req.params) ?? { content: [] };
        }
        throw new Error(`unexpected method ${req.method}`);
      },
    ),
  } as unknown as Client;
}

describe("buildToolName", () => {
  it.each([
    ["mcp", "github", "create_issue", "mcp_github_create_issue"],
    ["mcp", "my-server", "my-tool", "mcp_my_server_my_tool"],
    ["mcp", "srv", "weird.chars!here", "mcp_srv_weird_chars_here"],
  ])("builds %s + %s + %s", (prefix, server, tool, expected) => {
    expect(buildToolName(prefix, server, tool)).toBe(expected);
  });

  it("truncates long names to 64 chars with a stable hash suffix", () => {
    const longA = buildToolName("mcp", "server", "a".repeat(100));
    const longB = buildToolName("mcp", "server", `${"a".repeat(99)}b`);
    expect(longA.length).toBeLessThanOrEqual(64);
    expect(longB.length).toBeLessThanOrEqual(64);
    expect(longA).not.toBe(longB);
    // Deterministic across calls.
    expect(buildToolName("mcp", "server", "a".repeat(100))).toBe(longA);
  });
});

describe("convertMcpContent", () => {
  it.each([
    [
      "text",
      [{ type: "text", text: "hello" }],
      [{ type: "text", text: "hello" }],
    ],
    [
      "image passthrough",
      [{ type: "image", data: "aGk=", mimeType: "image/png" }],
      [{ type: "image", data: "aGk=", mimeType: "image/png" }],
    ],
    [
      "invalid image payload",
      [{ type: "image" }],
      [{ type: "text", text: "[Image: invalid payload]" }],
    ],
    [
      "audio described as text",
      [{ type: "audio", mimeType: "audio/mp3" }],
      [{ type: "text", text: "[Audio: audio/mp3, base64 encoded]" }],
    ],
    [
      "resource with text",
      [{ type: "resource", resource: { uri: "file:///a", text: "body" } }],
      [{ type: "text", text: "body" }],
    ],
    [
      "resource with blob",
      [{ type: "resource", resource: { uri: "file:///a", blob: "xxx" } }],
      [{ type: "text", text: "[Resource blob: file:///a]" }],
    ],
    [
      "unknown type serialized",
      [{ type: "mystery", value: 1 }],
      [{ type: "text", text: '{"type":"mystery","value":1}' }],
    ],
    ["non-object item", ["plain"], [{ type: "text", text: "plain" }]],
  ])("converts %s", (_label, input, expected) => {
    expect(convertMcpContent(input)).toEqual(expected);
  });
});

describe("listAllTools", () => {
  it("follows nextCursor pagination", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        tools: [{ name: "a", inputSchema: {} }],
        nextCursor: "page2",
      })
      .mockResolvedValueOnce({ tools: [{ name: "b", inputSchema: {} }] });
    const client = { request } as unknown as Client;

    const tools = await listAllTools(client, 1_000);
    expect(tools.map((t) => t.name)).toEqual(["a", "b"]);
    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls[1]?.[0]).toMatchObject({
      params: { cursor: "page2" },
    });
  });

  it("stops at the max page guard on a looping server", async () => {
    const request = vi.fn().mockResolvedValue({
      tools: [{ name: "loop", inputSchema: {} }],
      nextCursor: "again",
    });
    const client = { request } as unknown as Client;

    const tools = await listAllTools(client, 1_000);
    expect(request).toHaveBeenCalledTimes(100);
    expect(tools).toHaveLength(100);
  });
});

describe("truncateBridgedContent", () => {
  it("leaves small text and non-text content untouched", () => {
    const content: BridgedContent[] = [
      { type: "text", text: "hello" },
      { type: "image", data: "aGk=", mimeType: "image/png" },
    ];
    expect(truncateBridgedContent(content)).toEqual(content);
  });

  it("truncates a large text block and appends an explanatory note", () => {
    const bigText = "x".repeat(200_000);
    const [result] = truncateBridgedContent([{ type: "text", text: bigText }]);
    expect(result?.type).toBe("text");
    const text = (result as { text: string }).text;
    expect(text.length).toBeLessThan(bigText.length);
    expect(text).toContain("Output truncated");
    expect(text).toContain("Narrow the query/arguments");
  });
});

describe("ToolBridge", () => {
  it("registers and activates tools on refresh", async () => {
    const { host, registered, getActive } = fakeHost();
    const bridge = new ToolBridge(settings, host);
    const client = fakeClient({
      tools: [
        {
          name: "echo",
          description: "Echo text",
          inputSchema: {
            type: "object",
            properties: { text: { type: "string" } },
            required: ["text"],
          },
        },
      ],
    });

    await bridge.refreshTools("demo", client);

    expect(registered.has("mcp_demo_echo")).toBe(true);
    expect(registered.get("mcp_demo_echo")?.description).toBe("Echo text");
    // Args are surfaced in the TUI via a custom call renderer.
    expect(typeof registered.get("mcp_demo_echo")?.renderCall).toBe("function");
    expect(getActive()).toContain("mcp_demo_echo");
    // Pre-existing tools stay active.
    expect(getActive()).toContain("read");
  });

  it("appends annotation hints to descriptions", async () => {
    const { host, registered } = fakeHost();
    const bridge = new ToolBridge(settings, host);
    const client = fakeClient({
      tools: [
        {
          name: "drop_db",
          description: "Drops the database",
          inputSchema: {},
          annotations: { destructiveHint: true, openWorldHint: true },
        },
      ],
    });

    await bridge.refreshTools("demo", client);
    expect(registered.get("mcp_demo_drop_db")?.description).toBe(
      "Drops the database [destructive, interacts with external systems]",
    );
  });

  it("deactivates tools that disappear on refresh", async () => {
    const { host, getActive } = fakeHost();
    const bridge = new ToolBridge(settings, host);

    await bridge.refreshTools(
      "demo",
      fakeClient({
        tools: [
          { name: "a", inputSchema: {} },
          { name: "b", inputSchema: {} },
        ],
      }),
    );
    expect(getActive()).toContain("mcp_demo_a");
    expect(getActive()).toContain("mcp_demo_b");

    await bridge.refreshTools(
      "demo",
      fakeClient({ tools: [{ name: "a", inputSchema: {} }] }),
    );
    expect(getActive()).toContain("mcp_demo_a");
    expect(getActive()).not.toContain("mcp_demo_b");
  });

  it("records collisions per refresh and clears them on the next one", async () => {
    const { host } = fakeHost();
    const bridge = new ToolBridge(settings, host);

    await bridge.refreshTools(
      "demo",
      fakeClient({
        tools: [
          { name: "my-tool", inputSchema: {} },
          { name: "my_tool", inputSchema: {} },
        ],
      }),
    );
    // Both sides of the conflict are recorded — the shadowed first tool
    // ("my-tool") as well as the one that wins ("my_tool") — so a user
    // debugging a missing tool can see what happened to it.
    expect(bridge.getCollisions("demo")).toEqual([
      {
        serverName: "demo",
        mcpToolName: "my-tool",
        piToolName: "mcp_demo_my_tool",
      },
      {
        serverName: "demo",
        mcpToolName: "my_tool",
        piToolName: "mcp_demo_my_tool",
      },
    ]);
    expect(bridge.getCollisions("other")).toEqual([]);

    // A refresh without the colliding pair clears the record.
    await bridge.refreshTools(
      "demo",
      fakeClient({ tools: [{ name: "my_tool", inputSchema: {} }] }),
    );
    expect(bridge.getCollisions("demo")).toEqual([]);
  });

  it("reports the shadowed claimant only once for a three-way collision", async () => {
    const { host } = fakeHost();
    const bridge = new ToolBridge(settings, host);

    await bridge.refreshTools(
      "demo",
      fakeClient({
        tools: [
          { name: "my-tool", inputSchema: {} },
          { name: "my_tool", inputSchema: {} },
          { name: "my.tool", inputSchema: {} },
        ],
      }),
    );
    expect(bridge.getCollisions("demo")).toEqual([
      {
        serverName: "demo",
        mcpToolName: "my-tool",
        piToolName: "mcp_demo_my_tool",
      },
      {
        serverName: "demo",
        mcpToolName: "my_tool",
        piToolName: "mcp_demo_my_tool",
      },
      {
        serverName: "demo",
        mcpToolName: "my.tool",
        piToolName: "mcp_demo_my_tool",
      },
    ]);
  });

  it("deactivateServer removes only that server's tools", async () => {
    const { host, getActive } = fakeHost();
    const bridge = new ToolBridge(settings, host);
    await bridge.refreshTools(
      "one",
      fakeClient({ tools: [{ name: "a", inputSchema: {} }] }),
    );
    await bridge.refreshTools(
      "two",
      fakeClient({ tools: [{ name: "b", inputSchema: {} }] }),
    );

    bridge.deactivateServer("one");
    expect(getActive()).not.toContain("mcp_one_a");
    expect(getActive()).toContain("mcp_two_b");
    expect(getActive()).toContain("read");
  });

  it("reactivates tools after deactivation", async () => {
    const { host, getActive } = fakeHost();
    const bridge = new ToolBridge(settings, host);
    await bridge.refreshTools(
      "demo",
      fakeClient({ tools: [{ name: "a", inputSchema: {} }] }),
    );

    bridge.deactivateServer("demo");
    expect(getActive()).not.toContain("mcp_demo_a");
    bridge.activateServer("demo");
    expect(getActive()).toContain("mcp_demo_a");
  });

  it("wraps tools/list failures in McpError with code protocol", async () => {
    const { host } = fakeHost();
    const bridge = new ToolBridge(settings, host);
    const client = {
      request: vi.fn().mockRejectedValue(new Error("boom")),
    } as unknown as Client;

    await expect(bridge.refreshTools("demo", client)).rejects.toMatchObject({
      name: "McpError",
      code: "protocol",
      server: "demo",
    });
  });

  describe("bridged execute", () => {
    it("truncates a large tool result before it reaches the model (regression)", async () => {
      // Render-level collapsing (render.ts) only affects what the TUI
      // displays — it must not be the only thing standing between a large
      // MCP tool result (e.g. a broad SQL query) and the model's context.
      const { host, registered } = fakeHost();
      const bridge = new ToolBridge(settings, host);
      const bigOutput = Array.from(
        { length: 5_000 },
        (_, i) => `row ${i}`,
      ).join("\n");
      await bridge.refreshTools(
        "demo",
        fakeClient({
          tools: [{ name: "dump", inputSchema: {} }],
          onCall: () => ({ content: [{ type: "text", text: bigOutput }] }),
        }),
      );

      const result = await registered.get("mcp_demo_dump")?.execute("id-1", {});
      const text = (result?.content[0] as { text: string }).text;
      expect(text.length).toBeLessThan(bigOutput.length);
      expect(text).toContain("row 0");
      expect(text).not.toContain("row 4999");
      expect(text).toContain("Output truncated");
    });

    it("forwards arguments and converts result content", async () => {
      const { host, registered } = fakeHost();
      const bridge = new ToolBridge(settings, host);
      const onCall = vi.fn().mockReturnValue({
        content: [{ type: "text", text: "hi jonathan" }],
      });
      await bridge.refreshTools(
        "demo",
        fakeClient({ tools: [{ name: "echo", inputSchema: {} }], onCall }),
      );

      const tool = registered.get("mcp_demo_echo");
      const result = await tool?.execute("id-1", { text: "hi" });
      expect(onCall).toHaveBeenCalledWith({
        name: "echo",
        arguments: { text: "hi" },
      });
      expect(result?.content).toEqual([{ type: "text", text: "hi jonathan" }]);
    });

    it("throws McpError with code tool when the server reports isError", async () => {
      const { host, registered } = fakeHost();
      const bridge = new ToolBridge(settings, host);
      await bridge.refreshTools(
        "demo",
        fakeClient({
          tools: [{ name: "fail", inputSchema: {} }],
          onCall: () => ({
            content: [{ type: "text", text: "it broke" }],
            isError: true,
          }),
        }),
      );

      await expect(
        registered.get("mcp_demo_fail")?.execute("id-1", {}),
      ).rejects.toMatchObject({ name: "McpError", code: "tool" });
      await expect(
        registered.get("mcp_demo_fail")?.execute("id-1", {}),
      ).rejects.toThrowError(/it broke/);
    });

    it("wraps protocol failures in McpError with code protocol", async () => {
      const { host, registered } = fakeHost();
      const bridge = new ToolBridge(settings, host);
      const client = fakeClient({ tools: [{ name: "echo", inputSchema: {} }] });
      await bridge.refreshTools("demo", client);
      (client.request as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("timeout"),
      );

      await expect(
        registered.get("mcp_demo_echo")?.execute("id-1", {}),
      ).rejects.toMatchObject({ name: "McpError", code: "protocol" });
    });

    it("short-circuits when the signal is already aborted", async () => {
      const { host, registered } = fakeHost();
      const bridge = new ToolBridge(settings, host);
      const onCall = vi.fn();
      await bridge.refreshTools(
        "demo",
        fakeClient({ tools: [{ name: "echo", inputSchema: {} }], onCall }),
      );

      const controller = new AbortController();
      controller.abort();
      const result = await registered
        .get("mcp_demo_echo")
        ?.execute("id-1", {}, controller.signal);
      expect(result?.content).toEqual([{ type: "text", text: "Cancelled" }]);
      expect(onCall).not.toHaveBeenCalled();
    });
  });

  it("McpError userMessage includes the server name", () => {
    const err = new McpError("boom", "demo", "tool");
    expect(err.userMessage).toBe("[demo] boom");
  });
});
