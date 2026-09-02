import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseConfig } from "./config";
import { createMcpProxyTool, type ProxyToolDeps } from "./proxy-tool";
import { ServerManager } from "./server-manager";
import type { MockMcpServer } from "./test-support";
import { createMockMcpServer } from "./test-support";
import type { ToolBridgeHost } from "./tool-bridge";
import { ToolBridge } from "./tool-bridge";
import { McpToolCache } from "./tool-cache";

const ECHO_TOOL = {
  name: "echo",
  description: "Echo text back",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
  },
  handler: (args: Record<string, unknown>) => ({
    content: [{ type: "text", text: `echo: ${String(args.text)}` }],
  }),
};

function fakeHost(): { host: ToolBridgeHost; getActive: () => string[] } {
  const known = new Set<string>();
  let active: string[] = [];
  const host = {
    // Matches real pi (`agent-session.js` `_refreshToolRegistry`): a
    // brand-new tool name is auto-activated the instant it's registered.
    // ToolBridge.activateServer() must correct for this even when a server
    // has nothing to explicitly add (directTools: false/[]).
    registerTool: (tool: unknown) => {
      const name = (tool as { name: string }).name;
      const isNew = !known.has(name);
      known.add(name);
      if (isNew && !active.includes(name)) active = [...active, name];
    },
    getActiveTools: () => [...active],
    setActiveTools: (names: string[]) => {
      active = [...names];
    },
  } as unknown as ToolBridgeHost;
  return { host, getActive: () => active };
}

async function setup(options: {
  servers: Record<string, unknown>;
  mock: MockMcpServer;
  cacheDir: string;
}) {
  const config = parseConfig({ mcpServers: options.servers }, "test");
  const manager = new ServerManager(config, {
    transportFactory: options.mock.transportFactory,
  });
  const { host } = fakeHost();
  const toolCache = new McpToolCache(join(options.cacheDir, "cache.json"));
  const bridge = new ToolBridge(config.settings, host, { toolCache });
  manager.setToolRefreshCallback(async (serverName, client) => {
    await bridge.refreshTools(
      serverName,
      client,
      manager.getRequestTimeoutMs(serverName),
      manager.getServer(serverName)?.config,
    );
  });
  manager.setDisconnectCallback((serverName) => {
    bridge.deactivateServer(serverName);
  });

  const deps: ProxyToolDeps = {
    getManager: () => manager,
    getBridge: () => bridge,
    getToolCache: () => toolCache,
    getSettings: () => config.settings,
    getCwd: () => "/workspace",
    authHint: (serverName, message) =>
      /unauthorized|401/i.test(message) ? ` — run /mcp:auth ${serverName}` : "",
  };
  const tool = createMcpProxyTool(deps);
  return { manager, bridge, toolCache, tool, deps };
}

async function text(
  tool: ReturnType<typeof createMcpProxyTool>,
  params: Record<string, unknown>,
): Promise<string> {
  const result = await tool.execute(
    "id-1",
    params as never,
    undefined,
    undefined as never,
    undefined as never,
  );
  return (result.content[0] as { text: string }).text;
}

describe("mcp proxy tool", () => {
  let cacheDir: string;

  beforeEach(async () => {
    cacheDir = await mkdtemp(join(tmpdir(), "mcp-proxy-"));
  });

  afterEach(async () => {
    // The tool cache writes fire-and-forget (best effort); a write racing
    // this cleanup can otherwise trip ENOTEMPTY on rmdir.
    await rm(cacheDir, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 20,
    });
  });

  it("reports no servers configured when nothing is set up", async () => {
    const deps: ProxyToolDeps = {
      getManager: () => null,
      getBridge: () => null,
      getToolCache: () => null,
      getSettings: () => null,
      getCwd: () => "/workspace",
      authHint: () => "",
    };
    const tool = createMcpProxyTool(deps);
    expect(await text(tool, { search: "anything" })).toMatch(
      /no MCP servers configured/,
    );
  });

  it("finds already-connected tools by keyword", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { manager, tool } = await setup({
      servers: { demo: { command: "unused", directTools: false } },
      mock,
      cacheDir,
    });
    await manager.startServer("demo", "/workspace");

    const result = await text(tool, { search: "echo text" });
    expect(result).toContain("mcp_demo_echo");
    expect(result).toContain("Echo text back");
    await mock.close();
  });

  it("truncates a very long tool description in search results", async () => {
    const longDescription = `Echo text back. ${"x".repeat(2_000)}`;
    const mock = createMockMcpServer([
      { ...ECHO_TOOL, description: longDescription },
    ]);
    const { manager, tool } = await setup({
      servers: { demo: { command: "unused", directTools: false } },
      mock,
      cacheDir,
    });
    await manager.startServer("demo", "/workspace");

    const result = await text(tool, { search: "echo" });
    expect(result.length).toBeLessThan(500);
    expect(result).toContain("mcp_demo_echo");
    expect(result).toContain("…");
    await mock.close();
  });

  it("truncates hit descriptions in structured details too, not just the model-facing text (regression)", async () => {
    // The `details.hits` returned alongside `content` feed the TUI renderer
    // (render.ts) directly — truncating only the formatted text string and
    // leaving the structured Hit objects untruncated would print a
    // server's full, possibly multi-page tool description in the terminal
    // no matter what Ctrl+O (expand/collapse) does.
    const longDescription = `Echo text back. ${"x".repeat(2_000)}`;
    const mock = createMockMcpServer([
      { ...ECHO_TOOL, description: longDescription },
    ]);
    const { manager, tool } = await setup({
      servers: { demo: { command: "unused", directTools: false } },
      mock,
      cacheDir,
    });
    await manager.startServer("demo", "/workspace");

    const result = await tool.execute(
      "id-1",
      { search: "echo" } as never,
      undefined,
      undefined as never,
      undefined as never,
    );
    const details = result.details as { hits?: Array<{ description: string }> };
    expect(details.hits).toHaveLength(1);
    expect(details.hits?.[0]?.description.length).toBeLessThan(300);
    expect(details.hits?.[0]?.description).toContain("…");
    await mock.close();
  });

  it("surfaces a not-yet-connected lazy server by its config description", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { tool } = await setup({
      servers: {
        demo: {
          command: "unused",
          lifecycle: "lazy",
          description: "Handles echoing things back",
        },
      },
      mock,
      cacheDir,
    });

    const result = await text(tool, { search: "echoing" });
    expect(result).toContain("demo (server, not connected)");
    expect(result).toContain('mcp({ tool: "demo" })');
    await mock.close();
  });

  it("finds cached tools for a stopped lazy server without connecting", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { manager, tool, toolCache } = await setup({
      servers: { demo: { command: "unused", lifecycle: "lazy" } },
      mock,
      cacheDir,
    });
    // Simulate a previous session having connected and cached the catalog.
    await toolCache.set("demo", {
      configHash: "irrelevant-for-search",
      tools: [
        {
          name: "mcp_demo_echo",
          mcpName: "echo",
          description: "Echo text back",
        },
      ],
    });

    const result = await text(tool, { search: "echo" });
    expect(result).toContain("mcp_demo_echo (not connected");
    expect(mock.connectionCount()).toBe(0);
    expect(manager.getServer("demo")?.state).toBe("stopped");
    await mock.close();
  });

  it("never dumps a large catalog into context on connect-by-server-name (regression)", async () => {
    // Real-world trigger: a server with hundreds of tools and long
    // descriptions (e.g. PostHog's MCP, ~650 tools) previously blew the
    // discovery response past 500KB in one tool result.
    const manyTools = Array.from({ length: 200 }, (_, i) => ({
      name: `tool_${i}`,
      description: "x".repeat(2_000),
      inputSchema: { type: "object", properties: {} },
      handler: () => ({ content: [{ type: "text", text: "ok" }] }),
    }));
    const mock = createMockMcpServer(manyTools);
    const { tool } = await setup({
      servers: { demo: { command: "unused", lifecycle: "lazy" } },
      mock,
      cacheDir,
    });

    const result = await text(tool, { tool: "demo" });
    expect(result.length).toBeLessThan(1_000);
    expect(result).toContain("200 tools discovered");
    expect(result).toContain("mcp({ search");
    await mock.close();
  });

  it("connecting by exact server name discovers tools without executing one", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { manager, tool } = await setup({
      servers: { demo: { command: "unused", lifecycle: "lazy" } },
      mock,
      cacheDir,
    });

    const result = await text(tool, { tool: "demo" });
    expect(result).toContain('connected to "demo"');
    expect(result).toContain("1 tool discovered");
    // Must never dump the full catalog into the tool result (context bloat).
    expect(result).not.toContain("mcp_demo_echo");
    expect(manager.getServer("demo")?.state).toBe("ready");
    await mock.close();
  });

  it("calling an already-live tool name dispatches directly", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { manager, tool } = await setup({
      servers: { demo: { command: "unused" } },
      mock,
      cacheDir,
    });
    await manager.startServer("demo", "/workspace");

    const result = await text(tool, {
      tool: "mcp_demo_echo",
      args: '{"text":"hi"}',
    });
    expect(result).toBe("echo: hi");
    await mock.close();
  });

  it("calling a cached tool name starts the owning lazy server on demand", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { manager, tool, toolCache } = await setup({
      servers: { demo: { command: "unused", lifecycle: "lazy" } },
      mock,
      cacheDir,
    });
    await toolCache.set("demo", {
      configHash: "irrelevant-for-lookup",
      tools: [
        {
          name: "mcp_demo_echo",
          mcpName: "echo",
          description: "Echo text back",
        },
      ],
    });
    expect(manager.getServer("demo")?.state).toBe("stopped");

    const result = await text(tool, {
      tool: "mcp_demo_echo",
      args: '{"text":"hello"}',
    });
    expect(result).toBe("echo: hello");
    expect(manager.getServer("demo")?.state).toBe("ready");
    await mock.close();
  });

  it("rejects invalid JSON args", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { manager, tool } = await setup({
      servers: { demo: { command: "unused" } },
      mock,
      cacheDir,
    });
    await manager.startServer("demo", "/workspace");

    const result = await text(tool, {
      tool: "mcp_demo_echo",
      args: "{not json",
    });
    expect(result).toMatch(/not valid JSON/);
    await mock.close();
  });

  it("rejects an unknown tool/server name", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { tool } = await setup({
      servers: { demo: { command: "unused" } },
      mock,
      cacheDir,
    });

    const result = await text(tool, { tool: "mcp_demo_missing" });
    expect(result).toMatch(/no tool or server named "mcp_demo_missing"/);
    await mock.close();
  });

  it("reads the tool cache file once per search, not once per non-ready server (regression)", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { tool, toolCache } = await setup({
      servers: {
        one: { command: "unused", lifecycle: "lazy" },
        two: { command: "unused", lifecycle: "lazy" },
        three: { command: "unused", lifecycle: "lazy" },
      },
      mock,
      cacheDir,
    });
    for (const name of ["one", "two", "three"]) {
      await toolCache.set(name, {
        configHash: "irrelevant-for-search",
        tools: [
          { name: `mcp_${name}_echo`, mcpName: "echo", description: "Echo" },
        ],
      });
    }

    const allSpy = vi.spyOn(McpToolCache.prototype, "all");
    const getSpy = vi.spyOn(McpToolCache.prototype, "get");
    try {
      const result = await text(tool, { search: "echo" });
      expect(result).toContain("mcp_one_echo");
      expect(result).toContain("mcp_two_echo");
      expect(result).toContain("mcp_three_echo");
      // One read for the whole search, regardless of how many non-ready
      // servers had a cached entry to check — not the previous N-reads-for-
      // N-servers behavior via a per-server `get()`.
      expect(allSpy).toHaveBeenCalledTimes(1);
      expect(getSpy).not.toHaveBeenCalled();
    } finally {
      allSpy.mockRestore();
      getSpy.mockRestore();
    }
    await mock.close();
  });

  it('reports a timeout, not "unknown error", when waiting for an already-starting server exceeds the deadline (regression)', async () => {
    // `lastError` is null while a server is merely still starting (it
    // hasn't failed) — falling through to `lastError?.message ?? "unknown
    // error"` on a timeout used to surface a meaningless message instead of
    // saying what actually happened.
    const config = parseConfig(
      { mcpServers: { demo: { command: "unused" } } },
      "test",
    );
    const manager = new ServerManager(config, {
      // Never resolves: connect() sets state to "starting" synchronously,
      // then hangs here forever, so the server never reaches "ready".
      transportFactory: () => new Promise(() => {}),
    });
    const { host } = fakeHost();
    const bridge = new ToolBridge(config.settings, host);
    const deps: ProxyToolDeps = {
      getManager: () => manager,
      getBridge: () => bridge,
      getToolCache: () => null,
      getSettings: () => config.settings,
      getCwd: () => "/workspace",
      authHint: () => "",
    };
    const tool = createMcpProxyTool(deps);

    // Fire the real start (unawaited): synchronously flips state to
    // "starting" before this function yields control back here.
    void manager.startServer("demo", "/workspace");
    expect(manager.getServer("demo")?.state).toBe("starting");

    vi.useFakeTimers();
    try {
      const resultPromise = text(tool, { tool: "demo" });
      await vi.advanceTimersByTimeAsync(30_100);
      const result = await resultPromise;
      expect(result).toMatch(/timed out waiting for server to start/);
      expect(result).not.toMatch(/unknown error/);
    } finally {
      vi.useRealTimers();
    }
  });

  it("surfaces the /mcp:auth hint when a lazy OAuth server fails to start", async () => {
    const { tool } = await setup({
      servers: {
        demo: {
          transport: "streamable-http",
          url: "https://mcp.example.com/mcp",
          lifecycle: "lazy",
          auth: { type: "oauth" },
        },
      },
      mock: createMockMcpServer([]),
      cacheDir,
    });
    // Force a start failure by using a transport factory that always throws
    // — rebuild with that transport instead of the mock's.
    const config = parseConfig(
      {
        mcpServers: {
          demo: {
            transport: "streamable-http",
            url: "https://mcp.example.com/mcp",
            lifecycle: "lazy",
            auth: { type: "oauth" },
          },
        },
      },
      "test",
    );
    config.settings.maxRetries = 0;
    const manager = new ServerManager(config, {
      transportFactory: async () => {
        throw new Error("HTTP 401 Unauthorized");
      },
      retryDelaysMs: [0],
    });
    const { host } = fakeHost();
    const bridge = new ToolBridge(config.settings, host);
    const deps: ProxyToolDeps = {
      getManager: () => manager,
      getBridge: () => bridge,
      getToolCache: () => null,
      getSettings: () => config.settings,
      getCwd: () => "/workspace",
      authHint: (serverName, message) =>
        /unauthorized|401/i.test(message)
          ? ` — run /mcp:auth ${serverName}`
          : "",
    };
    const authTool = createMcpProxyTool(deps);
    void tool;

    const result = await text(authTool, { tool: "demo" });
    expect(result).toMatch(/failed to start "demo"/);
    expect(result).toMatch(/run \/mcp:auth demo/);
  });
});
