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

/** Points nextInitPromise at a deferred the test settles once the refresh has
 *  reached its init await (after `vi.waitFor` on createdQueries). */
function deferInit() {
  let resolve!: (result: InitResult) => void;
  let reject!: (error: Error) => void;
  nextInitPromise = new Promise<InitResult>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { resolve, reject };
}

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

interface ClientMocks {
  sessionUpdate: ReturnType<typeof vi.fn>;
  extNotification: ReturnType<typeof vi.fn>;
}

function makeAgent(): { agent: Agent; client: ClientMocks } {
  const client: ClientMocks = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  };
  const agent = new ClaudeAcpAgent(client as unknown as AgentSideConnection);
  return { agent, client };
}

function findUpdate(
  client: ClientMocks,
  sessionUpdate: string,
): Record<string, unknown> | undefined {
  const match = client.sessionUpdate.mock.calls.find(
    ([call]) =>
      (call as { update?: { sessionUpdate?: string } }).update
        ?.sessionUpdate === sessionUpdate,
  );
  return (match?.[0] as { update: Record<string, unknown> } | undefined)
    ?.update;
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
    sdkSessionId: sessionId,
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
    input,
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
    const { agent } = makeAgent();
    await expect(agent.extMethod("_posthog/nope", {})).rejects.toThrow(
      /Method not found/i,
    );
  });

  it("rejects when payload has no refreshable fields", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-empty");

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {}),
    ).rejects.toThrow(/requires at least one refreshable field/);
  });

  it("rejects when mcpServers is not an array", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-malformed");

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
        mcpServers: "not-an-array",
      }),
    ).rejects.toThrow(/mcpServers must be an array/);
  });

  it("rejects refresh while a prompt is in flight", async () => {
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
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
      const { agent } = makeAgent();
      const { session } = installFakeSession(agent, "s-timeout");
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
      // The session is closed too, so a later prompt rejects SESSION_ENDED
      // instead of pushing into the retired input stream.
      expect((session as unknown as { queryClosed: boolean }).queryClosed).toBe(
        true,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("refuses a second refresh while one is already in progress", async () => {
    // ACP handlers are not serialized, so a second refresh can arrive at any
    // await point of the first. Racing two swaps against the same session
    // would orphan a live SDK query; the second must be refused.
    const { agent } = makeAgent();
    installFakeSession(agent, "s-concurrent-refresh");
    const init = deferInit();

    const first = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });
    // Let the first refresh reach its init await (one replacement query live).
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    await expect(
      agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
        mcpServers: freshMcpServers,
      }),
    ).rejects.toThrow(/query swap \(refresh or \/clear\) is in progress/);

    // The refused refresh started no second swap.
    expect(createdQueries).toHaveLength(1);

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(first).resolves.toEqual({ refreshed: true });
  });

  it("ignores a cancel that arrives while a refresh is in progress", async () => {
    // cancel() → interrupt() targets session.query, which mid-refresh is the
    // half-initialized replacement; interrupting it would corrupt the swap.
    const { agent } = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-cancel-mid-refresh");
    const init = deferInit();

    const refreshPromise = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    await agent.cancel({ sessionId: "s-cancel-mid-refresh" });

    // Neither the retired query nor the booting replacement is interrupted:
    // the replacement's interrupt would corrupt the swap, and the retired
    // query already had its one interrupt from retireQuery (count frozen
    // here while the cancel could add another).
    expect(createdQueries[0].interrupt).not.toHaveBeenCalled();
    expect(oldQuery.interrupt).toHaveBeenCalledTimes(1);

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(refreshPromise).resolves.toEqual({ refreshed: true });
  });

  it("holds a prompt that arrives mid-refresh and lands it on the fresh input stream", async () => {
    // A prompt racing the swap must wait for the refresh to settle instead of
    // pushing into the retired input stream, where it would be silently lost.
    // Watching every Pushable instance's push tells the streams apart without
    // touching Pushable's private queue.
    const { agent } = makeAgent();
    const { session, input: oldInput } = installFakeSession(
      agent,
      "s-prompt-mid-refresh",
    );
    const pushSpy = vi.spyOn(Pushable.prototype, "push");
    const init = deferInit();

    const refreshPromise = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));
    // Only the prompt's push is of interest; anything the swap itself pushed
    // would already have happened.
    pushSpy.mockClear();

    const promptPromise = agent.prompt({
      sessionId: "s-prompt-mid-refresh",
      prompt: [{ type: "text", text: "hello" }],
    });
    // The turn it queues never settles (the mocked query yields nothing);
    // swallow that so the test doesn't end on an unhandled rejection.
    promptPromise.catch(() => {});
    // Wait out a macrotask: the prompt's swap-gate await must NOT have run
    // its push yet.
    await new Promise((resolve) => setImmediate(resolve));
    expect(pushSpy).not.toHaveBeenCalled();

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(refreshPromise).resolves.toEqual({ refreshed: true });

    await vi.waitFor(() => expect(pushSpy).toHaveBeenCalledTimes(1));
    // The released prompt pushed into the fresh stream, not the retired one.
    expect((session as unknown as { input: Pushable<unknown> }).input).not.toBe(
      oldInput,
    );
    expect(pushSpy.mock.instances[0]).toBe(
      (session as unknown as { input: Pushable<unknown> }).input,
    );
    pushSpy.mockRestore();
  });

  it("refuses a /clear that arrives while a refresh is in progress", async () => {
    const { agent, client } = makeAgent();
    installFakeSession(agent, "s-clear-mid-refresh");
    const init = deferInit();

    const refreshPromise = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    const result = await agent.prompt({
      sessionId: "s-clear-mid-refresh",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(result.stopReason).toBe("end_turn");
    const chunk = findUpdate(client, "agent_message_chunk");
    expect((chunk?.content as { text?: string })?.text).toMatch(
      /already in progress/,
    );
    // The refused /clear started no second swap.
    expect(createdQueries).toHaveLength(1);

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(refreshPromise).resolves.toEqual({ refreshed: true });
  });

  it("drops a prompt whose pre-prompt await runs long enough for a refresh to start under it", async () => {
    // The prompt path awaits ensureLocalToolsConnected (a real RPC) before it
    // enqueues a turn, and the swap entry points refuse only once turnQueue
    // has an entry. So a refresh started mid-await sees "no in-flight turns"
    // and proceeds; the prompt, on the other side of the await, finds the
    // input stream now retiring and must not push the turn into the queue,
    // or it would strand there unsettled.
    const { agent } = makeAgent();
    const { session, input: oldInput } = installFakeSession(
      agent,
      "s-prompt-start-then-refresh",
    );
    let resolveStatus!: (value: unknown) => void;
    const statusBlocked = new Promise<unknown>((resolve) => {
      resolveStatus = resolve;
    });
    // Block the pre-prompt local-tools status check so the refresh can start
    // (and reach its own init await) while the prompt is parked on the await.
    (
      session as unknown as { query: { mcpServerStatus: unknown } }
    ).query.mcpServerStatus = vi.fn().mockImplementation(() => statusBlocked);
    const pushSpy = vi.spyOn(Pushable.prototype, "push");
    const init = deferInit();

    // Fire the prompt first; it parks on the status await before enqueue.
    const promptPromise = agent.prompt({
      sessionId: "s-prompt-start-then-refresh",
      prompt: [{ type: "text", text: "hello" }],
    });
    // Wait out a macrotask so the prompt reaches the blocked status await.
    await new Promise((resolve) => setImmediate(resolve));

    // With the prompt not yet enqueued (turnQueue is still empty), start the
    // refresh and let it reach the init await of its own replacement query.
    const refreshPromise = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    // Unblock the prompt's status await. On the other side, querySwap is
    // still set, so the prompt must fail before turnQueue.push rather than
    // strand the turn in the queue behind a retiring input stream.
    resolveStatus([{ name: "posthog-code-tools", status: "connected" }]);
    await expect(promptPromise).rejects.toThrow(/session has ended/i);

    // The turn never reached the queue, so nothing was pushed to either
    // stream and the refresh is free to settle on the fresh query.
    expect((session as unknown as { turnQueue: unknown[] }).turnQueue).toEqual(
      [],
    );
    expect(pushSpy).not.toHaveBeenCalled();

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(refreshPromise).resolves.toEqual({ refreshed: true });
    // Sanity: the swap really did replace the input stream the prompt was
    // about to write into. Without the guard the prompt's push would have
    // landed on the retired stream instead of failing.
    expect((session as unknown as { input: Pushable<unknown> }).input).not.toBe(
      oldInput,
    );
    pushSpy.mockRestore();
  });

  it("closes the session when the fresh session fails to initialize", async () => {
    // A non-timeout failure (SDK subprocess crash) must get the same
    // treatment as a timeout: terminate the unproven replacement and close
    // the session, so queryClosed gates every later prompt into SESSION_ENDED
    // instead of pushing into the retired input stream.
    const { agent } = makeAgent();
    const { session } = installFakeSession(agent, "s-init-crash");
    const init = deferInit();

    const refreshPromise = agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });
    const rejection = expect(refreshPromise).rejects.toThrow(
      /SDK subprocess crashed/,
    );
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));
    init.reject(new Error("SDK subprocess crashed"));
    await rejection;

    expect((session as unknown as { queryClosed: boolean }).queryClosed).toBe(
      true,
    );
    // The failed replacement query is torn down, not leaked.
    expect(createdQueries).toHaveLength(1);
    expect(createdQueries[0].close).toHaveBeenCalled();

    // A prompt after the failed swap gets a clean session-ended rejection.
    await expect(
      agent.prompt({
        sessionId: "s-init-crash",
        prompt: [{ type: "text", text: "hello" }],
      }),
    ).rejects.toThrow(/session has ended/);
  });

  it("swaps query/input/options and preserves session state", async () => {
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
    installFakeSession(agent, "s-model", { modelId });

    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: freshMcpServers,
    });

    expect(lastQueryCall.options?.model).toBe(expected);
  });

  it("rebuilds a FRESH in-process local-tools server across refresh", async () => {
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-healthy");
    oldQuery.mcpServerStatus.mockResolvedValue([
      { name: "posthog-code-tools", status: "connected" },
    ]);

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.setMcpServers).not.toHaveBeenCalled();
  });

  it("rebuilds and reconnects a fresh server when disconnected", async () => {
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
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
    const { agent } = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-missing");
    oldQuery.mcpServerStatus.mockResolvedValue([
      { name: "some-other", status: "connected" },
    ]);

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.setMcpServers).toHaveBeenCalledTimes(1);
  });

  it("does not block the turn when the status RPC fails", async () => {
    const { agent } = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-statuserr");
    oldQuery.mcpServerStatus.mockRejectedValue(new Error("rpc down"));

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.setMcpServers).not.toHaveBeenCalled();
  });

  it("does not block the turn when the status RPC hangs", async () => {
    vi.useFakeTimers();
    try {
      const { agent } = makeAgent();
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
    const { agent } = makeAgent();
    const { oldQuery } = installFakeSession(agent, "s-reconnect-fail");
    oldQuery.mcpServerStatus.mockResolvedValue(DISCONNECTED_STATUS);
    oldQuery.setMcpServers.mockRejectedValue(new Error("connect boom"));

    await expect(callHeal(agent)).resolves.toBe(false);
  });

  it("is a no-op when no in-process server is enabled", async () => {
    const { agent } = makeAgent();
    const { session, oldQuery } = installFakeSession(agent, "s-none");
    (
      session as unknown as { localToolsServerNames: string[] }
    ).localToolsServerNames = [];

    await expect(callHeal(agent)).resolves.toBe(true);
    expect(oldQuery.mcpServerStatus).not.toHaveBeenCalled();
  });
});
