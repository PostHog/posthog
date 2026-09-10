import { setTimeout as sleep } from "node:timers/promises";
import { describe, expect, it, vi } from "vitest";
import { McpAuthStorage } from "./auth-storage";
import type { McpConfig } from "./config";
import { parseConfig } from "./config";
import { McpOAuthProvider } from "./oauth-provider";
import type { TransportFactory } from "./server-manager";
import { ServerManager } from "./server-manager";
import { createMockMcpServer } from "./test-support";

function makeConfig(overrides: Record<string, unknown> = {}): McpConfig {
  return parseConfig(
    {
      settings: { maxRetries: 3, ...(overrides.settings as object) },
      mcpServers: {
        demo: { command: "unused" },
        ...(overrides.mcpServers as object),
      },
    },
    "test",
  );
}

const ECHO_TOOL = {
  name: "echo",
  handler: (args: Record<string, unknown>) => ({
    content: [{ type: "text", text: String(args.text ?? "") }],
  }),
};

describe("ServerManager", () => {
  it("connects, reaches ready, and triggers the tool refresh callback", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(makeConfig(), {
      transportFactory: mock.transportFactory,
    });
    const refresh = vi.fn().mockResolvedValue(undefined);
    manager.setToolRefreshCallback(refresh);

    await manager.startServer("demo", "/workspace");

    const server = manager.getServer("demo");
    expect(server?.state).toBe("ready");
    expect(server?.client).not.toBeNull();
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledWith("demo", server?.client);

    await manager.shutdownAll();
    await mock.close();
  });

  it("startServer is a no-op when already ready", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(makeConfig(), {
      transportFactory: mock.transportFactory,
    });
    await manager.startServer("demo", "/workspace");
    await manager.startServer("demo", "/workspace");
    expect(mock.connectionCount()).toBe(1);
    await manager.shutdownAll();
    await mock.close();
  });

  it("throws for unknown server names", async () => {
    const manager = new ServerManager(makeConfig());
    await expect(manager.startServer("nope", "/tmp")).rejects.toMatchObject({
      name: "McpError",
      code: "config",
    });
  });

  it("stopServer stops the server and clears the client", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(makeConfig(), {
      transportFactory: mock.transportFactory,
    });
    await manager.startServer("demo", "/workspace");
    await manager.stopServer("demo");

    const server = manager.getServer("demo");
    expect(server?.state).toBe("stopped");
    expect(server?.client).toBeNull();
    await mock.close();
  });

  it("retries in the background after a failed connect, then succeeds", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    let attempts = 0;
    const flaky: TransportFactory = async (name, config, appendLog) => {
      attempts++;
      if (attempts <= 2) throw new Error(`fail ${attempts}`);
      return mock.transportFactory(name, config, appendLog);
    };
    const manager = new ServerManager(makeConfig(), {
      transportFactory: flaky,
      retryDelaysMs: [5, 5],
    });

    await manager.startServer("demo", "/workspace");
    // First attempt failed; retries are scheduled in the background.
    expect(manager.getServer("demo")?.state).toBe("stopped");
    expect(manager.getServer("demo")?.lastError?.message).toBe("fail 1");

    await vi.waitFor(() => {
      expect(manager.getServer("demo")?.state).toBe("ready");
    });
    expect(attempts).toBe(3);
    expect(manager.getServerLogs("demo")).toContain("retrying in 5ms");

    await manager.shutdownAll();
    await mock.close();
  });

  it("gives up after maxRetries and records it in the log", async () => {
    const failing: TransportFactory = async () => {
      throw new Error("always fails");
    };
    const manager = new ServerManager(
      makeConfig({ settings: { maxRetries: 2 } }),
      { transportFactory: failing, retryDelaysMs: [1, 1] },
    );

    await manager.startServer("demo", "/workspace");
    await vi.waitFor(() => {
      expect(manager.getServerLogs("demo")).toContain(
        "giving up after 2 retries",
      );
    });
    expect(manager.getServer("demo")?.state).toBe("stopped");
  });

  it("stopServer cancels a pending retry", async () => {
    let attempts = 0;
    const failing: TransportFactory = async () => {
      attempts++;
      throw new Error("nope");
    };
    const manager = new ServerManager(makeConfig(), {
      transportFactory: failing,
      retryDelaysMs: [10],
    });

    await manager.startServer("demo", "/workspace");
    expect(attempts).toBe(1);
    await manager.stopServer("demo");
    await sleep(30);
    expect(attempts).toBe(1);
  });

  it("stopServer during an in-flight failing connect does not schedule a retry", async () => {
    let attempts = 0;
    let rejectConnect!: (err: Error) => void;
    const hanging: TransportFactory = () => {
      attempts++;
      return new Promise((_, reject) => {
        rejectConnect = reject;
      });
    };
    const manager = new ServerManager(makeConfig(), {
      transportFactory: hanging,
      retryDelaysMs: [1],
    });

    const startPromise = manager.startServer("demo", "/workspace");
    await manager.stopServer("demo");
    rejectConnect(new Error("boom"));
    await startPromise;
    await sleep(30);
    expect(attempts).toBe(1);
    expect(manager.getServer("demo")?.state).toBe("stopped");
  });

  it("responds to roots/list with the workspace cwd", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(makeConfig(), {
      transportFactory: mock.transportFactory,
    });
    await manager.startServer("demo", "/my/workspace");
    // Ask from the server side — exercises the client's roots/list handler
    // end-to-end over the in-memory transport.
    const roots = await mock.lastServer()?.listRoots();
    expect(roots?.roots).toEqual([
      { uri: "file:///my/workspace", name: "workspace" },
    ]);
    await manager.shutdownAll();
    await mock.close();
  });

  it("refreshes tools when the server sends tools/list_changed", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(makeConfig(), {
      transportFactory: mock.transportFactory,
    });
    const refresh = vi.fn().mockResolvedValue(undefined);
    manager.setToolRefreshCallback(refresh);

    await manager.startServer("demo", "/workspace");
    expect(refresh).toHaveBeenCalledTimes(1);

    await mock.setTools([
      ECHO_TOOL,
      { name: "extra", handler: () => ({ content: [] }) },
    ]);
    await vi.waitFor(() => {
      expect(refresh).toHaveBeenCalledTimes(2);
    });

    await manager.shutdownAll();
    await mock.close();
  });

  it("getStatusSummary reflects server states", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(
      makeConfig({ mcpServers: { second: { command: "unused" } } }),
      { transportFactory: mock.transportFactory },
    );
    await manager.startServer("demo", "/workspace");

    const summary = manager.getStatusSummary();
    expect(summary).toContain("MCP: 1/2 servers ready");
    expect(summary).toContain("✓ demo (ready)");
    expect(summary).toContain("✗ second (stopped)");

    await manager.shutdownAll();
    await mock.close();
  });

  it("getRequestTimeoutMs prefers the per-server override", () => {
    const manager = new ServerManager(
      makeConfig({
        settings: { requestTimeoutMs: 30_000 },
        mcpServers: { custom: { command: "unused", requestTimeoutMs: 1_000 } },
      }),
    );
    expect(manager.getRequestTimeoutMs("demo")).toBe(30_000);
    expect(manager.getRequestTimeoutMs("custom")).toBe(1_000);
  });

  describe("OAuth provider wiring", () => {
    const OAUTH_CONFIG = {
      mcpServers: {
        demo: {
          transport: "streamable-http",
          url: "https://mcp.example.com/mcp",
          auth: { type: "oauth" },
        },
      },
    };

    it("passes a background auth provider to the transport factory", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const seen: unknown[] = [];
      const factory: TransportFactory = (name, config, appendLog, provider) => {
        seen.push(provider);
        return mock.transportFactory(name, config, appendLog);
      };
      const manager = new ServerManager(parseConfig(OAUTH_CONFIG, "test"), {
        transportFactory: factory,
        authStorage: new McpAuthStorage("/tmp/unused-mcp-auth"),
      });
      await manager.startServer("demo", "/workspace");
      expect(seen[0]).toBeInstanceOf(McpOAuthProvider);
      await manager.shutdownAll();
      await mock.close();
    });

    it.each([
      [
        "no auth config",
        { mcpServers: { demo: { command: "unused" } } },
        new McpAuthStorage("/tmp/unused-mcp-auth"),
      ],
      ["no auth storage", OAUTH_CONFIG, undefined],
    ])(
      "passes no auth provider with %s",
      async (_label, rawConfig, authStorage) => {
        const mock = createMockMcpServer([ECHO_TOOL]);
        const seen: unknown[] = [];
        const factory: TransportFactory = (
          name,
          config,
          appendLog,
          provider,
        ) => {
          seen.push(provider);
          return mock.transportFactory(name, config, appendLog);
        };
        const manager = new ServerManager(parseConfig(rawConfig, "test"), {
          transportFactory: factory,
          ...(authStorage ? { authStorage } : {}),
        });
        await manager.startServer("demo", "/workspace");
        expect(seen[0]).toBeUndefined();
        await manager.shutdownAll();
        await mock.close();
      },
    );
  });

  describe("connection loss", () => {
    it("detects an unexpected disconnect, notifies, and reconnects", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const manager = new ServerManager(makeConfig(), {
        transportFactory: mock.transportFactory,
        retryDelaysMs: [5],
      });
      const onDisconnect = vi.fn();
      manager.setDisconnectCallback(onDisconnect);
      const refresh = vi.fn().mockResolvedValue(undefined);
      manager.setToolRefreshCallback(refresh);

      await manager.startServer("demo", "/workspace");
      expect(manager.getServer("demo")?.state).toBe("ready");

      // Simulate a server crash: closing the server side closes the
      // client's transport, firing client.onclose.
      await mock.lastServer()?.close();

      await vi.waitFor(() => {
        expect(onDisconnect).toHaveBeenCalledWith("demo");
      });
      await vi.waitFor(() => {
        expect(manager.getServer("demo")?.state).toBe("ready");
      });
      expect(mock.connectionCount()).toBe(2);
      expect(refresh).toHaveBeenCalledTimes(2);
      expect(manager.getServerLogs("demo")).toContain(
        "connection closed unexpectedly",
      );

      await manager.shutdownAll();
      await mock.close();
    });

    it("does not treat an intentional stop as a disconnect", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const manager = new ServerManager(makeConfig(), {
        transportFactory: mock.transportFactory,
        retryDelaysMs: [1],
      });
      const onDisconnect = vi.fn();
      manager.setDisconnectCallback(onDisconnect);

      await manager.startServer("demo", "/workspace");
      await manager.stopServer("demo");
      await sleep(20);

      expect(onDisconnect).not.toHaveBeenCalled();
      expect(mock.connectionCount()).toBe(1);
      await mock.close();
    });

    it("health-check failure triggers disconnect handling and reconnect", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const manager = new ServerManager(
        makeConfig({
          mcpServers: {
            demo: { command: "unused", healthCheckIntervalMs: 10 },
          },
        }),
        { transportFactory: mock.transportFactory, retryDelaysMs: [5] },
      );
      const onDisconnect = vi.fn();
      manager.setDisconnectCallback(onDisconnect);

      await manager.startServer("demo", "/workspace");
      const client = manager.getServer("demo")?.client;
      expect(client).not.toBeNull();
      // Make pings fail without closing the transport (a hung server).
      vi.spyOn(
        client as unknown as { ping: () => Promise<unknown> },
        "ping",
      ).mockRejectedValue(new Error("timeout"));

      await vi.waitFor(() => {
        expect(onDisconnect).toHaveBeenCalledWith("demo");
      });
      await vi.waitFor(() => {
        expect(mock.connectionCount()).toBe(2);
        expect(manager.getServer("demo")?.state).toBe("ready");
      });
      expect(manager.getServerLogs("demo")).toContain("health check failed");

      await manager.shutdownAll();
      await mock.close();
    });
  });

  describe("idle timeout", () => {
    it("disconnects a lazy server that has been idle past idleTimeoutMs", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const manager = new ServerManager(
        makeConfig({
          mcpServers: {
            demo: {
              command: "unused",
              lifecycle: "lazy",
              idleTimeoutMs: 20,
            },
          },
        }),
        { transportFactory: mock.transportFactory },
      );

      await manager.startServer("demo", "/workspace");
      expect(manager.getServer("demo")?.state).toBe("ready");

      await vi.waitFor(
        () => {
          expect(manager.getServer("demo")?.state).toBe("stopped");
        },
        { timeout: 2_000 },
      );
      // Idle disconnect must not schedule a reconnect (unlike a crash).
      await sleep(50);
      expect(mock.connectionCount()).toBe(1);
      await mock.close();
    });

    it("touch() resets the idle countdown", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const manager = new ServerManager(
        makeConfig({
          mcpServers: {
            demo: {
              command: "unused",
              lifecycle: "lazy",
              idleTimeoutMs: 30,
            },
          },
        }),
        { transportFactory: mock.transportFactory },
      );

      await manager.startServer("demo", "/workspace");
      const touchInterval = setInterval(() => manager.touch("demo"), 10);
      await sleep(80);
      clearInterval(touchInterval);
      expect(manager.getServer("demo")?.state).toBe("ready");

      await vi.waitFor(
        () => {
          expect(manager.getServer("demo")?.state).toBe("stopped");
        },
        { timeout: 2_000 },
      );
      await mock.close();
    });

    it("never applies to eager servers", async () => {
      const mock = createMockMcpServer([ECHO_TOOL]);
      const manager = new ServerManager(
        makeConfig({
          mcpServers: {
            demo: {
              command: "unused",
              lifecycle: "eager",
              idleTimeoutMs: 15,
            },
          },
        }),
        { transportFactory: mock.transportFactory },
      );

      await manager.startServer("demo", "/workspace");
      await sleep(60);
      expect(manager.getServer("demo")?.state).toBe("ready");

      await manager.shutdownAll();
      await mock.close();
    });
  });

  it("closes the orphan client when stop races a succeeding connect", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const gated: TransportFactory = async (name, config, appendLog) => {
      await gate;
      return mock.transportFactory(name, config, appendLog);
    };
    const manager = new ServerManager(makeConfig(), {
      transportFactory: gated,
    });
    const refresh = vi.fn().mockResolvedValue(undefined);
    manager.setToolRefreshCallback(refresh);

    const startPromise = manager.startServer("demo", "/workspace");
    await manager.stopServer("demo");
    release();
    await startPromise;

    const server = manager.getServer("demo");
    expect(server?.state).toBe("stopped");
    expect(server?.client).toBeNull();
    expect(refresh).not.toHaveBeenCalled();
    await mock.close();
  });

  it("keeps the server ready with lastError when initial tool registration fails", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    const manager = new ServerManager(makeConfig(), {
      transportFactory: mock.transportFactory,
    });
    manager.setToolRefreshCallback(
      vi.fn().mockRejectedValue(new Error("tools/list exploded")),
    );

    await manager.startServer("demo", "/workspace");

    const server = manager.getServer("demo");
    expect(server?.state).toBe("ready");
    expect(server?.lastError?.message).toBe("tools/list exploded");
    expect(manager.getServerLogs("demo")).toContain(
      "initial tool registration failed",
    );
    await manager.shutdownAll();
    await mock.close();
  });

  it("startServer reconnects after retries were exhausted", async () => {
    const mock = createMockMcpServer([ECHO_TOOL]);
    let failing = true;
    const flaky: TransportFactory = async (name, config, appendLog) => {
      if (failing) throw new Error("still down");
      return mock.transportFactory(name, config, appendLog);
    };
    const manager = new ServerManager(
      makeConfig({ settings: { maxRetries: 1 } }),
      { transportFactory: flaky, retryDelaysMs: [1] },
    );

    await manager.startServer("demo", "/workspace");
    await vi.waitFor(() => {
      expect(manager.getServerLogs("demo")).toContain(
        "giving up after 1 retries",
      );
    });

    // Explicit start resets the retry budget and connects.
    failing = false;
    await manager.startServer("demo", "/workspace");
    expect(manager.getServer("demo")?.state).toBe("ready");
    await manager.shutdownAll();
    await mock.close();
  });
});
