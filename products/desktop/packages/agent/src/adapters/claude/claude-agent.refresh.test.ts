import {
  type AgentSideConnection,
  RequestError,
} from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POSTHOG_METHODS } from "../../acp-extensions";
import { Pushable } from "../../utils/streams";

type InitResult = {
  result: "success";
  commands?: unknown[];
  models?: unknown[];
};

type SdkQueryHandle = {
  interrupt: ReturnType<typeof vi.fn>;
  setModel: ReturnType<typeof vi.fn>;
  setMcpServers: ReturnType<typeof vi.fn>;
  mcpServerStatus: ReturnType<typeof vi.fn>;
  supportedCommands: ReturnType<typeof vi.fn>;
  initializationResult: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  [Symbol.asyncIterator]: () => AsyncIterator<never>;
};

let nextInitPromise: Promise<InitResult> = Promise.resolve({
  result: "success",
  commands: [],
  models: [],
});

function makeQueryHandle(): SdkQueryHandle {
  return {
    interrupt: vi.fn().mockResolvedValue(undefined),
    setModel: vi.fn().mockResolvedValue(undefined),
    setMcpServers: vi.fn().mockResolvedValue(undefined),
    mcpServerStatus: vi.fn().mockResolvedValue([]),
    supportedCommands: vi.fn().mockResolvedValue([]),
    initializationResult: vi.fn().mockImplementation(() => nextInitPromise),
    close: vi.fn(),
    [Symbol.asyncIterator]: async function* () {
      /* never yields */
    } as never,
  };
}

const lastQueryCall: { options?: Record<string, unknown> } = {};
const createdQueries: SdkQueryHandle[] = [];

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn((params: { options: Record<string, unknown> }) => {
    lastQueryCall.options = params.options;
    const handle = makeQueryHandle();
    createdQueries.push(handle);
    return handle;
  }),
}));

const fetchMcpToolMetadataMock = vi.fn().mockResolvedValue(undefined);
const clearMcpToolMetadataCacheMock = vi.fn();
vi.mock("./mcp/tool-metadata", () => ({
  fetchMcpToolMetadata: fetchMcpToolMetadataMock,
  getConnectedMcpServerNames: vi.fn().mockReturnValue([]),
  getCachedMcpTools: vi.fn().mockReturnValue([]),
  clearMcpToolMetadataCache: clearMcpToolMetadataCacheMock,
}));

// Import after the mocks so ClaudeAcpAgent resolves the mocked SDK
const { ClaudeAcpAgent } = await import("./claude-agent");
type Agent = InstanceType<typeof ClaudeAcpAgent>;

function makeAgent(): Agent {
  const client = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  } as unknown as AgentSideConnection;
  return new ClaudeAcpAgent(client);
}

function installFakeSession(
  agent: Agent,
  sessionId: string,
  overrides: Partial<{ modelId: string }> = {},
) {
  const oldQuery = makeQueryHandle();
  const input = new Pushable();
  const endSpy = vi.spyOn(input, "end");
  const abortController = new AbortController();

  // Distinguishable fresh instance per call so tests can prove a rebuild.
  let freshInstanceCounter = 0;
  const buildInProcessMcpServers = vi.fn(() => ({
    "posthog-code-tools": {
      type: "sdk" as const,
      name: "posthog-code-tools",
      instance: { fresh: ++freshInstanceCounter },
    },
  }));

  const session = {
    query: oldQuery,
    queryOptions: {
      sessionId,
      cwd: "/tmp/repo",
      model: "claude-sonnet-4-6",
      mcpServers: {
        posthog: { type: "http", url: "https://old" },
        "posthog-code-tools": {
          type: "sdk",
          name: "posthog-code-tools",
          instance: { stale: true },
        },
      },
      abortController,
    },
    buildInProcessMcpServers,
    localToolsServerNames: ["posthog-code-tools"],
    input,
    cancelled: false,
    settingsManager: { dispose: vi.fn() },
    permissionMode: "default",
    abortController,
    accumulatedUsage: {
      inputTokens: 42,
      outputTokens: 17,
      cachedReadTokens: 0,
      cachedWriteTokens: 0,
    },
    sessionResources: new Set(),
    configOptions: [],
    turnQueue: [],
    activeTurn: null,
    pendingOrphanResults: 0,
    queryGeneration: 0,
    cwd: "/tmp/repo",
    notificationHistory: [{ foo: "bar" }],
    taskRunId: "run-1",
    modelId: overrides.modelId,
  } as unknown as Parameters<typeof Object.assign>[0];

  (agent as unknown as { session: unknown }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return {
    session,
    oldQuery,
    endSpy,
    abortController,
    buildInProcessMcpServers,
  };
}

const freshMcpServers = [
  {
    name: "posthog",
    type: "http" as const,
    url: "https://fresh",
    headers: [{ name: "x-foo", value: "bar" }],
  },
];

describe("ClaudeAcpAgent.extMethod refresh_session", () => {
  beforeEach(() => {
    lastQueryCall.options = undefined;
    createdQueries.length = 0;
    nextInitPromise = Promise.resolve({
      result: "success",
      commands: [],
      models: [],
    });
    fetchMcpToolMetadataMock.mockClear();
    clearMcpToolMetadataCacheMock.mockClear();
  });

  it("returns methodNotFound for unknown extension methods", async () => {
    const agent = makeAgent();
    await expect(agent.extMethod("_posthog/nope", {})).rejects.toThrow(
      /Method not found/i,
    );
  });

  it("rejects when payload has no refreshable fields", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-empty");

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {}),
    ).rejects.toThrow(/requires at least one refreshable field/);
  });

  it("rejects when mcpServers is not an array", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-malformed");

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
        mcpServers: "not-an-array",
      }),
    ).rejects.toThrow(/mcpServers must be an array/);
  });

  it("rejects refresh while a prompt is in flight", async () => {
    const agent = makeAgent();
    const { session } = installFakeSession(agent, "s-1");
    (session as unknown as { turnQueue: unknown[] }).turnQueue = [
      { promptUuid: "u-1", settled: false },
    ];

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
        mcpServers: freshMcpServers,
      }),
    ).rejects.toThrow(/prompt turn is in flight/);
  });

  it("rejects when session model does not support MCP injection", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-haiku", { modelId: "claude-haiku-4-5" });

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
        mcpServers: freshMcpServers,
      }),
    ).rejects.toThrow(/does not support MCP injection/);
  });

  it("throws a RequestError and closes the timed-out query so it cannot leak", async () => {
    vi.useFakeTimers();
    try {
      const agent = makeAgent();
      installFakeSession(agent, "s-timeout");
      // Never resolves — withTimeout must win the race.
      nextInitPromise = new Promise<InitResult>(() => {});

      const promise = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
        mcpServers: freshMcpServers,
      });
      // Drop the rejection on the floor so an unhandled-rejection warning
      // doesn't race the assertion below.
      promise.catch(() => {});

      await vi.advanceTimersByTimeAsync(30_001);

      // A RequestError (not a plain Error) is what survives the ACP layer
      // instead of being collapsed into a generic "Internal error".
      await expect(promise).rejects.toBeInstanceOf(RequestError);
      await expect(promise).rejects.toThrow(/Session refresh timed out after/);
      // The new query is closed so its CLI subprocess does not leak.
      expect(createdQueries[0]?.close).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("swaps query/input/options and preserves session state", async () => {
    const agent = makeAgent();
    const { session, oldQuery, endSpy } = installFakeSession(agent, "s-2");

    const result = await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(result).toEqual({ refreshed: true });
    expect(oldQuery.interrupt).toHaveBeenCalledTimes(1);
    expect(endSpy).toHaveBeenCalledTimes(1);

    // New query: resume identity (not sessionId), http server refreshed, and
    // the in-process local-tools server rebuilt fresh.
    expect(lastQueryCall.options).toMatchObject({
      resume: "s-2",
      forkSession: false,
      mcpServers: {
        posthog: {
          type: "http",
          url: "https://fresh",
          headers: { "x-foo": "bar" },
        },
        "posthog-code-tools": {
          type: "sdk",
          name: "posthog-code-tools",
          instance: {},
        },
      },
    });
    expect(lastQueryCall.options?.sessionId).toBeUndefined();

    // Session fields swapped to the new instances
    const updated = session as unknown as {
      query: SdkQueryHandle;
      input: unknown;
      queryOptions: Record<string, unknown>;
      accumulatedUsage: { inputTokens: number };
      notificationHistory: unknown[];
    };
    expect(updated.query).toBe(createdQueries[0]);
    expect(updated.query).not.toBe(oldQuery);
    expect(updated.input).toBeInstanceOf(Pushable);
    expect(updated.queryOptions).toBe(lastQueryCall.options);

    // Preserves session-level state (usage, notification history)
    expect(updated.accumulatedUsage.inputTokens).toBe(42);
    expect(updated.notificationHistory).toEqual([{ foo: "bar" }]);
  });

  it("aborts the old controller and allocates a fresh one for the new query", async () => {
    const agent = makeAgent();
    const { session, abortController: oldController } = installFakeSession(
      agent,
      "s-abort",
    );

    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(oldController.signal.aborted).toBe(true);

    const updated = session as unknown as {
      abortController: AbortController;
      queryOptions: { abortController: AbortController };
    };
    expect(updated.abortController).not.toBe(oldController);
    expect(updated.abortController.signal.aborted).toBe(false);
    expect(updated.queryOptions.abortController).toBe(updated.abortController);
    expect(lastQueryCall.options?.abortController).toBe(
      updated.abortController,
    );
  });

  it("recovers when interrupting the old query throws Operation aborted", async () => {
    const agent = makeAgent();
    const { session, oldQuery, endSpy } = installFakeSession(
      agent,
      "s-interrupt-throws",
    );
    oldQuery.interrupt.mockRejectedValue(new Error("Operation aborted"));

    const result = await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(result).toEqual({ refreshed: true });
    expect(endSpy).toHaveBeenCalledTimes(1);
    const updated = session as unknown as {
      query: SdkQueryHandle;
      abortController: AbortController;
    };
    expect(updated.query).toBe(createdQueries[0]);
    expect(updated.query).not.toBe(oldQuery);
    expect(updated.abortController.signal.aborted).toBe(false);
  });

  it("re-fetches MCP tool metadata for the new query", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-metadata");

    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(fetchMcpToolMetadataMock).toHaveBeenCalledTimes(1);
    expect(fetchMcpToolMetadataMock.mock.calls[0][0]).toBe(createdQueries[0]);
  });

  // The fake session is created on sonnet (queryOptions.model); modelId
  // simulates the user switching models mid-session.
  it.each([
    {
      name: "re-roots the new query on the live session model",
      modelId: "claude-fable-5",
      expected: "claude-fable-5",
    },
    {
      name: "maps the live session model to its SDK alias",
      modelId: "claude-opus-4-8",
      expected: "opus",
    },
    {
      name: "keeps the creation-time model when the session has no modelId",
      modelId: undefined,
      expected: "claude-sonnet-4-6",
    },
  ])("$name", async ({ modelId, expected }) => {
    const agent = makeAgent();
    installFakeSession(agent, "s-model", { modelId });

    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(lastQueryCall.options?.model).toBe(expected);
  });

  it("rebuilds a FRESH in-process local-tools server across refresh", async () => {
    const agent = makeAgent();
    const { session, buildInProcessMcpServers } = installFakeSession(
      agent,
      "s-inprocess",
    );
    const staleInstance = (
      session as unknown as {
        queryOptions: { mcpServers: Record<string, { instance?: unknown }> };
      }
    ).queryOptions.mcpServers["posthog-code-tools"].instance;

    // freshMcpServers carries only external servers; the sdk server is rebuilt.
    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(buildInProcessMcpServers).toHaveBeenCalledTimes(1);
    const servers = lastQueryCall.options?.mcpServers as Record<
      string,
      { type?: string; name?: string; instance?: unknown }
    >;
    expect(servers["posthog-code-tools"]).toMatchObject({
      type: "sdk",
      name: "posthog-code-tools",
    });
    // A brand-new instance object, never the stale reused one.
    expect(servers["posthog-code-tools"].instance).not.toBe(staleInstance);
    expect(servers["posthog-code-tools"].instance).toEqual({ fresh: 1 });
  });

  it("clears the MCP tool metadata cache on refresh", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-cache");

    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(clearMcpToolMetadataCacheMock).toHaveBeenCalledTimes(1);
  });
});

const DISCONNECTED_STATUS = [{ name: "posthog-code-tools", status: "failed" }];

describe("ClaudeAcpAgent self-heal: ensureLocalToolsConnected", () => {
  beforeEach(() => {
    clearMcpToolMetadataCacheMock.mockClear();
    fetchMcpToolMetadataMock.mockClear();
  });

  function callHeal(agent: Agent, trigger = "test"): Promise<boolean> {
    return (
      agent as unknown as {
        ensureLocalToolsConnected: (t: string) => Promise<boolean>;
      }
    ).ensureLocalToolsConnected(trigger);
  }

  it("is a no-op when the signed-commit server is connected", async () => {
    const agent = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-healthy");
    oldQuery.mcpServerStatus.mockResolvedValue([
      { name: "posthog-code-tools", status: "connected" },
    ]);

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.setMcpServers).not.toHaveBeenCalled();
  });

  it("rebuilds and reconnects a fresh server when disconnected", async () => {
    const agent = makeAgent();
    const { session, oldQuery, buildInProcessMcpServers } = installFakeSession(
      agent,
      "s-down",
    );
    oldQuery.mcpServerStatus.mockResolvedValue(DISCONNECTED_STATUS);

    await expect(callHeal(agent)).resolves.toBe(true);

    expect(buildInProcessMcpServers).toHaveBeenCalledTimes(1);
    expect(oldQuery.setMcpServers).toHaveBeenCalledTimes(1);
    const arg = oldQuery.setMcpServers.mock.calls[0][0] as Record<
      string,
      { type?: string; instance?: unknown }
    >;
    // External http server passed through unchanged; sdk server is fresh.
    expect(arg.posthog).toMatchObject({ type: "http" });
    expect(arg["posthog-code-tools"]).toMatchObject({ type: "sdk" });
    expect(arg["posthog-code-tools"].instance).toEqual({ fresh: 1 });
    expect(clearMcpToolMetadataCacheMock).toHaveBeenCalledTimes(1);
    // queryOptions is updated so later heals/refresh see the fresh server set.
    expect(
      (session as unknown as { queryOptions: { mcpServers: unknown } })
        .queryOptions.mcpServers,
    ).toBe(arg);
  });

  it("passes every external server through when reconnecting", async () => {
    const agent = makeAgent();
    const { session, oldQuery } = installFakeSession(agent, "s-multi");
    (
      session as unknown as {
        queryOptions: { mcpServers: Record<string, unknown> };
      }
    ).queryOptions.mcpServers = {
      posthog: { type: "http", url: "https://old" },
      sentry: { type: "sse", url: "https://sse" },
      "posthog-code-tools": {
        type: "sdk",
        name: "posthog-code-tools",
        instance: { stale: true },
      },
    };
    oldQuery.mcpServerStatus.mockResolvedValue(DISCONNECTED_STATUS);

    await expect(callHeal(agent)).resolves.toBe(true);

    const arg = oldQuery.setMcpServers.mock.calls[0][0] as Record<
      string,
      { type?: string }
    >;
    expect(Object.keys(arg).sort()).toEqual([
      "posthog",
      "posthog-code-tools",
      "sentry",
    ]);
    expect(arg.posthog).toMatchObject({ type: "http" });
    expect(arg.sentry).toMatchObject({ type: "sse" });
    expect(arg["posthog-code-tools"]).toMatchObject({ type: "sdk" });
  });

  it("treats a server missing from status as disconnected", async () => {
    const agent = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-missing");
    oldQuery.mcpServerStatus.mockResolvedValue([
      { name: "some-other", status: "connected" },
    ]);

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.setMcpServers).toHaveBeenCalledTimes(1);
  });

  it("does not block the turn when the status RPC fails", async () => {
    const agent = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-statuserr");
    oldQuery.mcpServerStatus.mockRejectedValue(new Error("rpc down"));

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.setMcpServers).not.toHaveBeenCalled();
  });

  it("does not block the turn when the status RPC hangs", async () => {
    vi.useFakeTimers();
    try {
      const agent = makeAgent();
      const { oldQuery } = installFakeSession(agent, "s-statushang");
      oldQuery.mcpServerStatus.mockReturnValue(new Promise(() => {}));

      const healPromise = callHeal(agent);
      await vi.advanceTimersByTimeAsync(5_001);

      await expect(healPromise).resolves.toBe(true);
      expect(oldQuery.setMcpServers).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns false when reconnect fails", async () => {
    const agent = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-reconnect-fail");
    oldQuery.mcpServerStatus.mockResolvedValue(DISCONNECTED_STATUS);
    oldQuery.setMcpServers.mockRejectedValue(new Error("connect boom"));

    await expect(callHeal(agent)).resolves.toBe(false);
  });

  it("is a no-op when no in-process server is enabled", async () => {
    const agent = makeAgent();
    const { session, oldQuery } = installFakeSession(agent, "s-none");
    (
      session as unknown as { localToolsServerNames: string[] }
    ).localToolsServerNames = [];

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.mcpServerStatus).not.toHaveBeenCalled();
  });
});
