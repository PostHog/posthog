import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
  ExtensionAPI,
  ExtensionCommandContext,
  ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import { describe, expect, it, vi } from "vitest";
import { McpAuthStorage } from "./auth-storage";
import { parseConfig } from "./config";
import { createMcpExtension, openBrowser } from "./extension";
import type { MockMcpServer } from "./test-support";
import { createMockMcpServer } from "./test-support";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
type CommandHandler = (args: string, ctx: unknown) => Promise<unknown>;

interface RegisteredTool {
  name: string;
  execute: (
    toolCallId: string,
    params: unknown,
    signal?: AbortSignal,
  ) => Promise<{ content: Array<{ type: string; text?: string }> }>;
}

function fakePi() {
  const handlers = new Map<string, Handler[]>();
  const commands = new Map<
    string,
    {
      handler: CommandHandler;
      getArgumentCompletions?: (prefix: string) => unknown;
    }
  >();
  const tools = new Map<string, RegisteredTool>();
  let active: string[] = ["read", "bash"];
  const activeHistory: string[][] = [];

  const sentUserMessages: Array<{ content: string; options?: unknown }> = [];
  const pi = {
    on: (event: string, handler: Handler) => {
      handlers.set(event, [...(handlers.get(event) ?? []), handler]);
    },
    sendUserMessage: (content: string, options?: unknown) => {
      sentUserMessages.push({ content, ...(options ? { options } : {}) });
    },
    registerCommand: (
      name: string,
      options: {
        handler: CommandHandler;
        getArgumentCompletions?: (prefix: string) => unknown;
      },
    ) => {
      commands.set(name, options);
    },
    registerTool: (tool: unknown) => {
      const t = tool as RegisteredTool;
      // Matches real pi (`agent-session.js` `_refreshToolRegistry`): a
      // brand-new tool name is auto-activated the instant it's registered;
      // re-registering an already-known name is not. Extensions that want
      // an inactive-by-default tool must explicitly deactivate it after.
      const isNew = !tools.has(t.name);
      tools.set(t.name, t);
      if (isNew && !active.includes(t.name)) {
        active = [...active, t.name];
        activeHistory.push([...active]);
      }
    },
    getActiveTools: () => [...active],
    setActiveTools: (names: string[]) => {
      active = [...names];
      activeHistory.push([...names]);
    },
  } as unknown as ExtensionAPI;

  const emit = async (event: string, payload: unknown, ctx: unknown) => {
    const results: unknown[] = [];
    for (const handler of handlers.get(event) ?? []) {
      results.push(await handler(payload, ctx));
    }
    return results;
  };

  return {
    pi,
    emit,
    commands,
    tools,
    getActive: () => active,
    activeHistory,
    sentUserMessages,
  };
}

/**
 * Wraps a transport so `close()` is a no-op: lets tests stop a server
 * without killing in-flight requests, to deterministically drive the
 * refresh-completes-after-stop race.
 */
function unclosable(inner: Transport): Transport {
  return {
    start: () => inner.start(),
    send: (message, options) => inner.send(message, options),
    close: async () => {},
    get onclose() {
      return inner.onclose;
    },
    set onclose(value) {
      inner.onclose = value;
    },
    get onerror() {
      return inner.onerror;
    },
    set onerror(value) {
      inner.onerror = value;
    },
    get onmessage() {
      return inner.onmessage;
    },
    set onmessage(value) {
      inner.onmessage = value;
    },
  } as Transport;
}

function fakeCtx(overrides: { cwd?: string; trusted?: boolean } = {}) {
  const notify = vi.fn();
  const ctx = {
    cwd: overrides.cwd ?? "/workspace",
    hasUI: true,
    isProjectTrusted: () => overrides.trusted ?? true,
    ui: { notify },
  } as unknown as ExtensionContext & ExtensionCommandContext;
  return { ctx, notify };
}

const ECHO_TOOL = {
  name: "echo",
  description: "Echo text back",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
  handler: (args: Record<string, unknown>) => ({
    content: [{ type: "text", text: `echo: ${String(args.text)}` }],
  }),
};

/** Deep-clones a value with every object's key insertion order reversed. */
function reverseKeyOrder(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(reverseKeyOrder);
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    const reordered: Record<string, unknown> = {};
    for (const [key, v] of entries.reverse()) {
      reordered[key] = reverseKeyOrder(v);
    }
    return reordered;
  }
  return value;
}

function setup(options: {
  mock: MockMcpServer;
  servers?: Record<string, unknown>;
  settings?: Record<string, unknown>;
}) {
  const { pi, emit, commands, tools, getActive } = fakePi();
  const config = parseConfig(
    {
      settings: options.settings ?? {},
      mcpServers: options.servers ?? {
        demo: { command: "unused", lifecycle: "eager", directTools: true },
      },
    },
    "test",
  );
  const configLoader = vi.fn().mockResolvedValue(config);
  createMcpExtension({
    configLoader,
    transportFactory: options.mock.transportFactory,
  })(pi);
  return { pi, emit, commands, tools, getActive, configLoader, config };
}

describe("createMcpExtension", () => {
  it("starts eager servers on session_start and exposes their tools", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, tools, getActive } = setup({ mock });
    const { ctx, notify } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);

    expect(getActive()).toContain("mcp_demo_echo");
    const tool = tools.get("mcp_demo_echo");
    const result = await tool?.execute("id-1", { text: "hello" });
    expect(result?.content).toEqual([{ type: "text", text: "echo: hello" }]);
    expect(notify).not.toHaveBeenCalled();

    await emit("session_shutdown", { reason: "quit" }, ctx);
    expect(getActive()).not.toContain("mcp_demo_echo");
    await mock.close();
  });

  it("registers the mcp proxy tool even with no servers configured", async () => {
    const { pi, emit, tools } = fakePi();
    createMcpExtension({
      configLoader: vi.fn().mockResolvedValue(parseConfig({}, "test")),
    })(pi);
    const { ctx } = fakeCtx();
    await emit("session_start", { reason: "startup" }, ctx);

    expect(tools.has("mcp")).toBe(true);
    const result = await tools.get("mcp")?.execute("id-1", { search: "x" });
    expect(result?.content[0]?.text).toMatch(/no MCP servers configured/);
  });

  it("mcp proxy tool starts a lazy server on demand and calls its tool", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, tools, getActive } = setup({
      mock,
      servers: { demo: { command: "unused", lifecycle: "lazy" } },
    });
    const { ctx } = fakeCtx();
    await emit("session_start", { reason: "startup" }, ctx);
    expect(mock.connectionCount()).toBe(0);

    // First use of a never-before-connected lazy server: connect by server
    // name. This must never dump the discovered catalog into context (a
    // real server can expose hundreds of tools) — just a count + a nudge
    // to use search.
    const discover = await tools.get("mcp")?.execute("id-1", { tool: "demo" });
    expect(discover?.content[0]).toMatchObject({
      text: expect.stringContaining("1 tool discovered"),
    });
    expect(discover?.content[0]).not.toMatchObject({
      text: expect.stringContaining("mcp_demo_echo"),
    });
    expect(mock.connectionCount()).toBe(1);

    const result = await tools
      .get("mcp")
      ?.execute("id-2", { tool: "mcp_demo_echo", args: '{"text":"hi"}' });
    expect(result?.content).toEqual([{ type: "text", text: "echo: hi" }]);
    // directTools defaults to false: calling through the proxy tool never
    // puts the tool's schema in context — the model only sees the result.
    expect(getActive()).not.toContain("mcp_demo_echo");

    await emit("session_shutdown", { reason: "quit" }, ctx);
    await mock.close();
  });

  it("directTools: false keeps a server's tools out of context until the proxy tool activates them", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, tools, getActive } = setup({
      mock,
      servers: {
        demo: { command: "unused", lifecycle: "eager", directTools: false },
      },
    });
    const { ctx } = fakeCtx();
    await emit("session_start", { reason: "startup" }, ctx);

    // Connected (eager), but not activated: schema stays out of context.
    expect(getActive()).not.toContain("mcp_demo_echo");

    const searchResult = await tools
      .get("mcp")
      ?.execute("id-1", { search: "echo" });
    expect(searchResult?.content[0]?.text).toContain("mcp_demo_echo");

    const callResult = await tools
      .get("mcp")
      ?.execute("id-2", { tool: "mcp_demo_echo", args: '{"text":"hi"}' });
    expect(callResult?.content).toEqual([{ type: "text", text: "echo: hi" }]);

    await emit("session_shutdown", { reason: "quit" }, ctx);
    await mock.close();
  });

  it("does not start lazy servers on session_start", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, getActive } = setup({
      mock,
      servers: { demo: { command: "unused", lifecycle: "lazy" } },
    });
    const { ctx } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(mock.connectionCount()).toBe(0);
    expect(getActive()).not.toContain("mcp_demo_echo");
    await mock.close();
  });

  it("passes project trust through to the config loader", async () => {
    const mock = createMockMcpServer([]);
    const { emit, configLoader } = setup({ mock, servers: {} });
    const { ctx } = fakeCtx({ trusted: false });

    await emit("session_start", { reason: "startup" }, ctx);
    expect(configLoader).toHaveBeenCalledWith("/workspace", {
      includeProject: false,
    });
  });

  it("notifies on config load errors instead of throwing", async () => {
    const { pi, emit } = fakePi();
    const configLoader = vi.fn().mockRejectedValue(new Error("bad config"));
    createMcpExtension({ configLoader })(pi);
    const { ctx, notify } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(notify).toHaveBeenCalledWith(
      expect.stringContaining("bad config"),
      "error",
    );
  });

  it("notifies when an eager server fails to start", async () => {
    const mock = createMockMcpServer([]);
    const { pi, emit } = fakePi();
    const config = parseConfig(
      {
        settings: { maxRetries: 0 },
        mcpServers: { broken: { command: "unused", lifecycle: "eager" } },
      },
      "test",
    );
    createMcpExtension({
      configLoader: vi.fn().mockResolvedValue(config),
      transportFactory: async () => {
        throw new Error("spawn failed");
      },
    })(pi);
    const { ctx, notify } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(notify).toHaveBeenCalledWith(
      expect.stringContaining("failed to start broken"),
      "error",
    );
    await mock.close();
  });

  describe("commands", () => {
    it("/mcp shows a status summary and per-server detail", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const { emit, commands } = setup({ mock });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp")?.handler("", ctx);
      expect(notify).toHaveBeenLastCalledWith(
        expect.stringContaining("MCP: 1/1 servers ready"),
        "info",
      );

      await commands.get("mcp")?.handler("demo", ctx);
      const detail = notify.mock.lastCall?.[0] as string;
      expect(detail).toContain("Server: demo");
      expect(detail).toContain("State:  ready");
      expect(detail).toContain("mcp_demo_echo");

      await commands.get("mcp")?.handler("missing", ctx);
      expect(notify).toHaveBeenLastCalledWith(
        'mcp: no server named "missing"',
        "error",
      );

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await mock.close();
    });

    it("/mcp reports when no servers are configured", async () => {
      const { pi, commands } = (() => {
        const fake = fakePi();
        createMcpExtension({
          configLoader: vi.fn().mockResolvedValue(parseConfig({}, "test")),
        })(fake.pi);
        return fake;
      })();
      void pi;
      const { ctx, notify } = fakeCtx();

      await commands.get("mcp")?.handler("", ctx);
      expect(notify).toHaveBeenCalledWith(
        expect.stringContaining("no servers configured"),
        "info",
      );
    });

    it("/mcp:start starts a lazy server and /mcp:stop deactivates it", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const { emit, commands, getActive } = setup({
        mock,
        servers: {
          demo: { command: "unused", lifecycle: "lazy", directTools: true },
        },
      });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp:start")?.handler("demo", ctx);
      expect(notify).toHaveBeenLastCalledWith("mcp: started demo", "info");
      expect(getActive()).toContain("mcp_demo_echo");

      await commands.get("mcp:stop")?.handler("demo", ctx);
      expect(notify).toHaveBeenLastCalledWith("mcp: stopped demo", "info");
      expect(getActive()).not.toContain("mcp_demo_echo");

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await mock.close();
    });

    it.each([["mcp:start"], ["mcp:stop"]])(
      "/%s validates arguments",
      async (command) => {
        const mock = createMockMcpServer([]);
        const { emit, commands } = setup({ mock });
        const { ctx, notify } = fakeCtx();
        await emit("session_start", { reason: "startup" }, ctx);

        await commands.get(command)?.handler("", ctx);
        expect(notify).toHaveBeenLastCalledWith(
          `Usage: /${command} <server-name>`,
          "error",
        );

        await commands.get(command)?.handler("missing", ctx);
        expect(notify).toHaveBeenLastCalledWith(
          'mcp: no server named "missing"',
          "error",
        );

        await emit("session_shutdown", { reason: "quit" }, ctx);
        await mock.close();
      },
    );

    it("completes server names for command arguments", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const { emit, commands } = setup({
        mock,
        servers: {
          alpha: { command: "unused", lifecycle: "lazy" },
          beta: { command: "unused", lifecycle: "lazy" },
        },
      });
      const { ctx } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      const completions = commands
        .get("mcp:start")
        ?.getArgumentCompletions?.("al") as Array<{ value: string }> | null;
      expect(completions?.map((c) => c.value)).toEqual(["alpha"]);
      await mock.close();
    });
  });

  it("does not re-activate tools when a refresh completes after stop", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { pi, emit, commands, getActive, activeHistory } = fakePi();
    createMcpExtension({
      configLoader: vi.fn().mockResolvedValue(
        parseConfig(
          {
            mcpServers: {
              demo: {
                command: "unused",
                lifecycle: "eager",
                directTools: true,
              },
            },
          },
          "test",
        ),
      ),
      // No-op close: stopping the server must not kill the gated in-flight
      // tools/list, so the refresh deterministically COMPLETES after stop
      // and exercises the re-activation guard (instead of just erroring).
      transportFactory: async (name, config, appendLog) =>
        unclosable(await mock.transportFactory(name, config, appendLog)),
    })(pi);
    const { ctx } = fakeCtx();
    await emit("session_start", { reason: "startup" }, ctx);
    expect(getActive()).toContain("mcp_demo_echo");
    const initialListCalls = mock.listToolsCalls();

    // Gate tools/list so the list_changed-triggered refresh stalls mid-flight.
    let release!: () => void;
    mock.setListToolsGate(
      new Promise<void>((resolve) => {
        release = resolve;
      }),
    );
    await mock.setTools([
      ECHO_TOOL,
      { name: "late", handler: () => ({ content: [] }) },
    ]);
    await vi.waitFor(() => {
      expect(mock.listToolsCalls()).toBeGreaterThan(initialListCalls);
    });

    // Stop the server while the refresh is blocked, then let it finish.
    await commands.get("mcp:stop")?.handler("demo", ctx);
    const historyAtStop = activeHistory.length;
    release();

    // Positive proof the race actually ran: the completed refresh must have
    // re-activated the server's tools (an activation entry appears after
    // stop) — without this, the assertions below would pass vacuously.
    await vi.waitFor(() => {
      const sinceStop = activeHistory.slice(historyAtStop);
      expect(sinceStop.some((names) => names.includes("mcp_demo_late"))).toBe(
        true,
      );
    });

    // ...and the guard must have deactivated them again.
    await vi.waitFor(() => {
      expect(getActive()).not.toContain("mcp_demo_echo");
      expect(getActive()).not.toContain("mcp_demo_late");
    });
    await mock.close();
  });

  describe("/mcp:auth", () => {
    const OAUTH_SERVER = {
      demo: {
        transport: "streamable-http",
        url: "https://mcp.example.com/mcp",
        lifecycle: "lazy",
        directTools: true,
        auth: { type: "oauth" },
      },
    };

    async function setupWithAuth(options: {
      servers?: Record<string, unknown>;
      flowResult?: "authorized" | "completed";
      flowError?: Error;
    }) {
      const dir = await mkdtemp(join(tmpdir(), "mcp-ext-auth-"));
      const authStorage = new McpAuthStorage(dir);
      const mock = createMockMcpServer([ECHO_TOOL]);
      const { pi, emit, commands, tools, getActive } = fakePi();
      const config = parseConfig(
        { mcpServers: options.servers ?? OAUTH_SERVER },
        "test",
      );
      const oauthFlow = vi.fn().mockImplementation(async () => {
        if (options.flowError) throw options.flowError;
        return options.flowResult ?? "completed";
      });
      createMcpExtension({
        configLoader: vi.fn().mockResolvedValue(config),
        transportFactory: mock.transportFactory,
        authStorage,
        oauthFlow,
      })(pi);
      return {
        pi,
        emit,
        commands,
        tools,
        getActive,
        oauthFlow,
        authStorage,
        mock,
        cleanup: async () => {
          await mock.close();
          await rm(dir, { recursive: true, force: true });
        },
      };
    }

    it("lists OAuth-enabled servers with auth status", async () => {
      const { emit, commands, authStorage, cleanup } = await setupWithAuth({});
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp:auth")?.handler("", ctx);
      let listing = notify.mock.lastCall?.[0] as string;
      expect(listing).toContain("demo: not authenticated");

      await authStorage.update("demo", "https://mcp.example.com/mcp", (e) => {
        e.tokens = { accessToken: "a", expiresAt: Date.now() / 1000 + 3600 };
        e.savedAt = Date.now();
      });
      await commands.get("mcp:auth")?.handler("", ctx);
      listing = notify.mock.lastCall?.[0] as string;
      expect(listing).toContain("demo: authenticated since");

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await cleanup();
    });

    it("reports when no servers have OAuth configured", async () => {
      const { emit, commands, cleanup } = await setupWithAuth({
        servers: { plain: { command: "unused", lifecycle: "lazy" } },
      });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp:auth")?.handler("", ctx);
      expect(notify).toHaveBeenLastCalledWith(
        expect.stringContaining("no servers with OAuth configured"),
        "info",
      );
      await cleanup();
    });

    it("runs the flow and starts the server on success", async () => {
      const { emit, commands, getActive, oauthFlow, cleanup } =
        await setupWithAuth({ flowResult: "completed" });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp:auth")?.handler("demo", ctx);

      expect(oauthFlow).toHaveBeenCalledTimes(1);
      expect(oauthFlow.mock.calls[0]?.[0]).toMatchObject({
        serverName: "demo",
        serverUrl: "https://mcp.example.com/mcp",
      });
      const messages = notify.mock.calls.map((call) => call[0] as string);
      expect(messages).toContain("mcp: demo authenticated successfully");
      expect(messages).toContain("mcp: started demo");
      expect(getActive()).toContain("mcp_demo_echo");

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await cleanup();
    });

    it("stops a running server before re-authenticating", async () => {
      const { emit, commands, getActive, cleanup } = await setupWithAuth({
        servers: {
          demo: { ...OAUTH_SERVER.demo, lifecycle: "eager" },
        },
        flowResult: "authorized",
      });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);
      expect(getActive()).toContain("mcp_demo_echo");

      await commands.get("mcp:auth")?.handler("demo", ctx);
      const messages = notify.mock.calls.map((call) => call[0] as string);
      expect(messages).toContain("mcp: demo already had valid credentials");
      expect(messages).toContain("mcp: started demo");

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await cleanup();
    });

    it("reset clears stored credentials before the flow", async () => {
      const { emit, commands, oauthFlow, authStorage, cleanup } =
        await setupWithAuth({ flowResult: "completed" });
      const { ctx } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);
      await authStorage.update("demo", "https://mcp.example.com/mcp", (e) => {
        e.tokens = { accessToken: "stale" };
      });

      await commands.get("mcp:auth")?.handler("demo reset", ctx);
      expect(await authStorage.read("demo")).toBeUndefined();
      expect(oauthFlow).toHaveBeenCalledTimes(1);

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await cleanup();
    });

    it("rejects a second /mcp:auth while one is already in flight", async () => {
      const dir = await mkdtemp(join(tmpdir(), "mcp-ext-auth-"));
      const mock = createMockMcpServer([]);
      const { pi, emit, commands } = fakePi();
      let release!: () => void;
      const oauthFlow = vi.fn().mockImplementation(
        () =>
          new Promise<"completed">((resolve) => {
            release = () => resolve("completed");
          }),
      );
      createMcpExtension({
        configLoader: vi
          .fn()
          .mockResolvedValue(parseConfig({ mcpServers: OAUTH_SERVER }, "test")),
        transportFactory: mock.transportFactory,
        authStorage: new McpAuthStorage(dir),
        oauthFlow,
      })(pi);
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      // First flow parks on the (deferred) browser wait.
      const firstFlow = commands.get("mcp:auth")?.handler("demo", ctx);
      await vi.waitFor(() => {
        expect(oauthFlow).toHaveBeenCalledTimes(1);
      });

      // Second invocation must be refused, not corrupt the first's state.
      await commands.get("mcp:auth")?.handler("demo", ctx);
      expect(notify).toHaveBeenLastCalledWith(
        expect.stringContaining("already in progress"),
        "error",
      );
      expect(oauthFlow).toHaveBeenCalledTimes(1);

      release();
      await firstFlow;
      // After completion a new flow is allowed again.
      oauthFlow.mockResolvedValue("authorized");
      await commands.get("mcp:auth")?.handler("demo", ctx);
      expect(oauthFlow).toHaveBeenCalledTimes(2);

      await emit("session_shutdown", { reason: "quit" }, ctx);
      await mock.close();
      await rm(dir, { recursive: true, force: true });
    });

    it("notifies on flow failure", async () => {
      const { emit, commands, cleanup } = await setupWithAuth({
        flowError: new Error("registration rejected"),
      });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp:auth")?.handler("demo", ctx);
      expect(notify).toHaveBeenLastCalledWith(
        expect.stringContaining(
          "authentication failed for demo — registration rejected",
        ),
        "error",
      );
      await cleanup();
    });

    it.each([
      ["unknown server", "missing", 'no server named "missing"'],
      ["server without oauth", "plain", "has no OAuth config"],
    ])("rejects %s", async (_label, target, message) => {
      const { emit, commands, cleanup } = await setupWithAuth({
        servers: {
          ...OAUTH_SERVER,
          plain: { command: "unused", lifecycle: "lazy" },
        },
      });
      const { ctx, notify } = fakeCtx();
      await emit("session_start", { reason: "startup" }, ctx);

      await commands.get("mcp:auth")?.handler(target, ctx);
      expect(notify).toHaveBeenLastCalledWith(
        expect.stringContaining(message),
        "error",
      );
      await cleanup();
    });
  });

  describe("openBrowser", () => {
    const URL_WITH_SEPARATORS =
      "https://auth.example.com/authorize?client_id=x&state=y&code_challenge=z";

    function withPlatform(platform: string, fn: () => Promise<void>) {
      const original = Object.getOwnPropertyDescriptor(
        process,
        "platform",
      ) as PropertyDescriptor;
      Object.defineProperty(process, "platform", { value: platform });
      return fn().finally(() => {
        Object.defineProperty(process, "platform", original);
      });
    }

    it.each([
      ["darwin", "open", [URL_WITH_SEPARATORS]],
      // Not `cmd /c start`: cmd.exe would treat the `&`s in the URL as
      // command separators (truncation + command injection).
      [
        "win32",
        "rundll32",
        ["url.dll,FileProtocolHandler", URL_WITH_SEPARATORS],
      ],
      ["linux", "xdg-open", [URL_WITH_SEPARATORS]],
    ])("uses injection-safe argv on %s", async (platform, command, args) =>
      withPlatform(platform, async () => {
        const exec = vi.fn().mockResolvedValue({ code: 0 });
        await openBrowser(
          { exec } as unknown as ExtensionAPI,
          URL_WITH_SEPARATORS,
        );
        expect(exec).toHaveBeenCalledWith(command, args);
      }),
    );

    it("throws when the opener exits nonzero", async () => {
      const exec = vi.fn().mockResolvedValue({ code: 1 });
      await expect(
        openBrowser({ exec } as unknown as ExtensionAPI, "https://x.example"),
      ).rejects.toThrowError(/Failed to open browser/);
    });
  });

  it("hints at /mcp:auth when an eager OAuth server fails with 401", async () => {
    const dir = await mkdtemp(join(tmpdir(), "mcp-ext-auth-"));
    const { pi, emit } = fakePi();
    const config = parseConfig(
      {
        settings: { maxRetries: 0 },
        mcpServers: {
          demo: {
            transport: "streamable-http",
            url: "https://mcp.example.com/mcp",
            lifecycle: "eager",
            auth: { type: "oauth" },
          },
        },
      },
      "test",
    );
    createMcpExtension({
      configLoader: vi.fn().mockResolvedValue(config),
      transportFactory: async () => {
        throw new Error("HTTP 401 Unauthorized");
      },
      authStorage: new McpAuthStorage(dir),
    })(pi);
    const { ctx, notify } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(notify).toHaveBeenCalledWith(
      expect.stringContaining("run /mcp:auth demo"),
      "error",
    );
    await rm(dir, { recursive: true, force: true });
  });

  describe("mcp_auth tool", () => {
    const OAUTH_SERVERS = {
      demo: {
        transport: "streamable-http",
        url: "https://mcp.example.com/mcp",
        lifecycle: "lazy",
        auth: { type: "oauth" },
      },
      plain: { command: "unused", lifecycle: "lazy" },
    };

    async function setupTool() {
      const mock = createMockMcpServer([]);
      const fake = fakePi();
      createMcpExtension({
        configLoader: vi
          .fn()
          .mockResolvedValue(
            parseConfig({ mcpServers: OAUTH_SERVERS }, "test"),
          ),
        transportFactory: mock.transportFactory,
      })(fake.pi);
      await fake.emit("session_start", { reason: "startup" }, fakeCtx().ctx);
      return { ...fake, mock };
    }

    it("queues /mcp:auth as a follow-up user message", async () => {
      const { tools, sentUserMessages, mock } = await setupTool();
      const result = await tools
        .get("mcp_auth")
        ?.execute("id-1", { server: "demo" });
      expect(sentUserMessages).toEqual([
        { content: "/mcp:auth demo", options: { deliverAs: "followUp" } },
      ]);
      expect(result?.content[0]).toMatchObject({ type: "text" });
      await mock.close();
    });

    it.each([
      ["unknown server", "missing", /No MCP server named "missing"/],
      ["server without oauth", "plain", /has no OAuth config/],
    ])("rejects %s", async (_label, server, message) => {
      const { tools, sentUserMessages, mock } = await setupTool();
      await expect(
        tools.get("mcp_auth")?.execute("id-1", { server }),
      ).rejects.toThrowError(message);
      expect(sentUserMessages).toHaveLength(0);
      await mock.close();
    });
  });

  it("does not duplicate the /mcp:auth hint when the error already contains it", async () => {
    const { pi, emit } = fakePi();
    const config = parseConfig(
      {
        settings: { maxRetries: 0 },
        mcpServers: {
          demo: {
            transport: "streamable-http",
            url: "https://mcp.example.com/mcp",
            lifecycle: "eager",
            auth: { type: "oauth" },
          },
        },
      },
      "test",
    );
    createMcpExtension({
      configLoader: vi.fn().mockResolvedValue(config),
      transportFactory: async () => {
        throw new Error(
          'Authentication required for MCP server "demo" — run /mcp:auth demo',
        );
      },
    })(pi);
    const { ctx, notify } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    const message = notify.mock.lastCall?.[0] as string;
    expect(message.match(/run \/mcp:auth demo/g)).toHaveLength(1);
  });

  it("deactivates tools when the server connection drops unexpectedly", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, getActive } = setup({ mock });
    const { ctx } = fakeCtx();
    await emit("session_start", { reason: "startup" }, ctx);
    expect(getActive()).toContain("mcp_demo_echo");

    // Crash the server: the disconnect callback must pull the tools.
    await mock.lastServer()?.close();
    await vi.waitFor(() => {
      expect(getActive()).not.toContain("mcp_demo_echo");
    });
    await mock.close();
  });

  it("bridged tools work against the new client after stop/start", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, commands, tools, getActive } = setup({ mock });
    const { ctx } = fakeCtx();
    await emit("session_start", { reason: "startup" }, ctx);

    const first = await tools
      .get("mcp_demo_echo")
      ?.execute("id-1", { text: "one" });
    expect(first?.content).toEqual([{ type: "text", text: "echo: one" }]);

    await commands.get("mcp:stop")?.handler("demo", ctx);
    await commands.get("mcp:start")?.handler("demo", ctx);
    expect(mock.connectionCount()).toBe(2);
    expect(getActive()).toContain("mcp_demo_echo");

    // The re-registered execute closure must be bound to the NEW client —
    // a stale closure would fail against the closed first connection.
    const second = await tools
      .get("mcp_demo_echo")
      ?.execute("id-2", { text: "two" });
    expect(second?.content).toEqual([{ type: "text", text: "echo: two" }]);

    await emit("session_shutdown", { reason: "quit" }, ctx);
    await mock.close();
  });

  it("does not restart servers when a resumed session has identical config", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit } = setup({ mock });
    const { ctx } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(mock.connectionCount()).toBe(1);

    // Identical config on resume: no teardown, no reconnect.
    await emit("session_start", { reason: "resume" }, ctx);
    expect(mock.connectionCount()).toBe(1);

    await emit("session_shutdown", { reason: "quit" }, ctx);
    await mock.close();
  });

  it("does not restart servers when config keys are merely reordered", async () => {
    // Zod preserves source key order, so a plain JSON.stringify comparison
    // would treat a config file with reordered (but unchanged) fields as a
    // change and needlessly tear down/rebuild the runtime on every resume.
    const mock = createMockMcpServer([ECHO_TOOL]);
    const { emit, configLoader, config } = setup({ mock });
    const { ctx } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(mock.connectionCount()).toBe(1);

    configLoader.mockResolvedValue(reverseKeyOrder(config) as typeof config);

    await emit("session_start", { reason: "resume" }, ctx);
    expect(mock.connectionCount()).toBe(1);

    await emit("session_shutdown", { reason: "quit" }, ctx);
    await mock.close();
  });

  it("contributes the bundled mcp-servers skill via resources_discover", async () => {
    const { pi, emit } = fakePi();
    createMcpExtension({
      configLoader: vi.fn().mockResolvedValue(parseConfig({}, "test")),
    })(pi);

    const results = (await emit(
      "resources_discover",
      { cwd: "/workspace", reason: "startup" },
      fakeCtx().ctx,
    )) as Array<{ skillPaths?: string[] }>;

    const skillPaths = results.flatMap((r) => r?.skillPaths ?? []);
    expect(skillPaths).toHaveLength(1);
    expect(skillPaths[0]).toMatch(/extensions[/\\]mcp[/\\]skills$/);
  });

  it("rebuilds the runtime when config changes between sessions", async () => {
    const mockA = createMockMcpServer([ECHO_TOOL]);
    const mockB = createMockMcpServer([{ ...ECHO_TOOL, name: "other" }]);
    const { pi, emit, getActive } = fakePi();
    const configA = parseConfig(
      {
        mcpServers: {
          demo: { command: "unused", lifecycle: "eager", directTools: true },
        },
      },
      "test",
    );
    const configB = parseConfig(
      {
        mcpServers: {
          second: { command: "unused", lifecycle: "eager", directTools: true },
        },
      },
      "test",
    );
    const configLoader = vi
      .fn()
      .mockResolvedValueOnce(configA)
      .mockResolvedValueOnce(configB);
    let currentMock = mockA;
    createMcpExtension({
      configLoader,
      transportFactory: (name, config, appendLog) =>
        currentMock.transportFactory(name, config, appendLog),
    })(pi);
    const { ctx } = fakeCtx();

    await emit("session_start", { reason: "startup" }, ctx);
    expect(getActive()).toContain("mcp_demo_echo");

    currentMock = mockB;
    await emit("session_start", { reason: "resume" }, ctx);
    expect(getActive()).not.toContain("mcp_demo_echo");
    expect(getActive()).toContain("mcp_second_other");

    await emit("session_shutdown", { reason: "quit" }, ctx);
    await mockA.close();
    await mockB.close();
  });
});
