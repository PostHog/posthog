import * as fs from "node:fs";
import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POSTHOG_METHODS, POSTHOG_NOTIFICATIONS } from "../../acp-extensions";
import { Pushable } from "../../utils/streams";
import { getSessionJsonlPath } from "./session/jsonl-hydration";
import { FALLBACK_MODEL } from "./session/models";

type InitResult = {
  result: "success";
  commands?: unknown[];
  models?: unknown[];
};

type SdkQueryHandle = {
  interrupt: ReturnType<typeof vi.fn>;
  setModel: ReturnType<typeof vi.fn>;
  setPermissionMode: ReturnType<typeof vi.fn>;
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
    setPermissionMode: vi.fn().mockResolvedValue(undefined),
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

/** Points nextInitPromise at a deferred the test settles once the clear has
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

vi.mock("./mcp/tool-metadata", () => ({
  fetchMcpToolMetadata: vi.fn().mockResolvedValue(undefined),
  getConnectedMcpServerNames: vi.fn().mockReturnValue([]),
  getCachedMcpTools: vi.fn().mockReturnValue([]),
  clearMcpToolMetadataCache: vi.fn(),
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

function installFakeSession(
  agent: Agent,
  sessionId: string,
  overrides: Partial<{ modelId: string; fallbackModel: string }> = {},
) {
  const oldQuery = makeQueryHandle();
  const input = new Pushable();
  const endSpy = vi.spyOn(input, "end");
  const abortController = new AbortController();

  const session = {
    query: oldQuery,
    sdkSessionId: sessionId,
    queryOptions: {
      sessionId,
      cwd: "/tmp/repo",
      permissionMode: "bypassPermissions",
      model: "claude-sonnet-4-6",
      fallbackModel: overrides.fallbackModel ?? FALLBACK_MODEL,
      mcpServers: {
        posthog: { type: "http", url: "https://posthog" },
        "posthog-code-tools": {
          type: "sdk",
          name: "posthog-code-tools",
          instance: { stale: true },
        },
      },
      abortController,
    },
    buildInProcessMcpServers: vi.fn(() => ({
      "posthog-code-tools": {
        type: "sdk" as const,
        name: "posthog-code-tools",
        instance: { fresh: true },
      },
    })),
    localToolsServerNames: ["posthog-code-tools"],
    input,
    cancelled: false,
    settingsManager: { dispose: vi.fn() },
    permissionMode: "default",
    abortController,
    accumulatedUsage: {
      inputTokens: 0,
      outputTokens: 0,
      cachedReadTokens: 0,
      cachedWriteTokens: 0,
    },
    sessionResources: new Set(),
    configOptions: [],
    turnQueue: [] as unknown[],
    activeTurn: null as unknown,
    pendingOrphanResults: 0,
    queryGeneration: 0,
    cwd: "/tmp/repo",
    notificationHistory: [] as unknown[],
    taskRunId: "run-1",
    lastContextWindowSize: 200_000,
    modelId: overrides.modelId ?? "claude-sonnet-4-6",
    taskState: new Map(),
  };

  (agent as unknown as { session: typeof session }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return { session, oldQuery, endSpy, abortController };
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

function findExtNotification(
  client: ClientMocks,
  method: string,
): Record<string, unknown> | undefined {
  const match = client.extNotification.mock.calls.find(
    ([calledMethod]) => calledMethod === method,
  );
  return match?.[1] as Record<string, unknown> | undefined;
}

function findAllExtNotifications(
  client: ClientMocks,
  method: string,
): Record<string, unknown>[] {
  return client.extNotification.mock.calls
    .filter(([calledMethod]) => calledMethod === method)
    .map(([, params]) => params as Record<string, unknown>);
}

describe("ClaudeAcpAgent /clear", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastQueryCall.options = undefined;
    createdQueries.length = 0;
    nextInitPromise = Promise.resolve({
      result: "success",
      commands: [],
      models: [],
    });
  });

  it("swaps in a fresh SDK session and emits the clear marker", async () => {
    const { agent, client } = makeAgent();
    const { session, oldQuery, endSpy } = installFakeSession(agent, "s-1");
    session.taskState.set("task-1", { title: "old task" });

    const result = await agent.prompt({
      sessionId: "s-1",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(result.stopReason).toBe("end_turn");

    // Old query retired, new query started fresh (no resume, new id).
    expect(oldQuery.interrupt).toHaveBeenCalledTimes(1);
    expect(endSpy).toHaveBeenCalledTimes(1);
    expect(createdQueries).toHaveLength(1);
    expect(lastQueryCall.options?.resume).toBeUndefined();
    const newSessionId = lastQueryCall.options?.sessionId as string;
    expect(newSessionId).toBeDefined();
    expect(newSessionId).not.toBe("s-1");

    // The in-process local-tools server is rebuilt fresh.
    const servers = lastQueryCall.options?.mcpServers as Record<
      string,
      { instance?: unknown }
    >;
    expect(servers["posthog-code-tools"].instance).toEqual({ fresh: true });
    expect(servers.posthog).toMatchObject({ type: "http" });

    // ACP identity is stable; the SDK session id diverges underneath.
    expect((agent as unknown as { sessionId: string }).sessionId).toBe("s-1");
    expect(session.sdkSessionId).toBe(newSessionId);
    expect(agent.hasSession("s-1")).toBe(true);
    expect(agent.hasSession(newSessionId)).toBe(true);

    // Repoints stored session ids and marks the boundary in the log.
    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.SDK_SESSION),
    ).toMatchObject({
      taskRunId: "run-1",
      sessionId: newSessionId,
      adapter: "claude",
    });
    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
    ).toMatchObject({ sessionId: newSessionId });

    // A "clearing" status opens immediately and closes on success, so the
    // user sees feedback for the whole swap even if it's slow.
    const statusNotifications = findAllExtNotifications(
      client,
      POSTHOG_NOTIFICATIONS.STATUS,
    );
    expect(statusNotifications).toEqual([
      { sessionId: "s-1", status: "clearing" },
      { sessionId: "s-1", status: "clearing", isComplete: true },
    ]);

    // The /clear prompt is echoed to the transcript, the plan panel resets,
    // and the context indicator drops to zero.
    expect(findUpdate(client, "user_message_chunk")).toMatchObject({
      content: { type: "text", text: "/clear" },
    });
    expect(session.taskState.size).toBe(0);
    expect(findUpdate(client, "plan")).toMatchObject({ entries: [] });
    expect(findUpdate(client, "usage_update")).toMatchObject({
      used: 0,
      size: 200_000,
    });
  });

  it("re-roots /clear on a pinned live model without colliding with its own fallback model", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-model", { modelId: "claude-opus-4-8" });

    await agent.prompt({
      sessionId: "s-model",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(lastQueryCall.options?.model).toBe("claude-opus-4-8");
    expect(lastQueryCall.options?.fallbackModel).toBeUndefined();
  });

  it("preserves a caller-configured fallback model across /clear", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-model", { fallbackModel: "claude-fable-5" });

    await agent.prompt({
      sessionId: "s-model",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(lastQueryCall.options?.fallbackModel).toBe("claude-fable-5");
  });

  it("clears when the host prepends hidden context ahead of the /clear, as cloud resumes do", async () => {
    // The cloud agent-server wraps a pending user message in a hidden resume
    // preamble. Reading the command off the first block of the prompt (or of
    // the converted SDK message, which also leads with host context) would
    // miss it and send "/clear" to the model as an ordinary turn.
    const { agent, client } = makeAgent();
    installFakeSession(agent, "s-cloud");

    const result = await agent.prompt({
      sessionId: "s-cloud",
      prompt: [
        {
          type: "text",
          text: "You are resuming a previous conversation. …",
          _meta: { ui: { hidden: true } },
        },
        { type: "text", text: "/clear" },
      ],
    });

    expect(result.stopReason).toBe("end_turn");
    expect(createdQueries).toHaveLength(1);
    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
    ).toBeDefined();
  });

  // A mode change updates the running query; queryOptions keeps the mode the session
  // was created with. Rebuilding from it silently hands back permissions the user had
  // since narrowed, and nothing on screen says the mode moved. Both paths that move
  // the mode have to keep queryOptions in step — setSessionMode and the plan-mode hook.
  it.each([
    {
      path: "applySessionMode",
      mode: "default",
      apply: (agent: Agent, mode: string) =>
        (
          agent as unknown as { applySessionMode: (m: string) => Promise<void> }
        ).applySessionMode(mode),
    },
    {
      path: "onModeChange",
      mode: "plan",
      apply: (agent: Agent, mode: string) =>
        (
          agent as unknown as {
            createOnModeChange: () => (m: string) => Promise<void>;
          }
        ).createOnModeChange()(mode),
    },
  ])(
    "carries the live permission mode into the fresh session via $path, not the creation-time one",
    async ({ mode, apply }) => {
      const { agent } = makeAgent();
      const { session } = installFakeSession(agent, "s-mode");
      await apply(agent, mode);

      await agent.prompt({
        sessionId: "s-mode",
        prompt: [{ type: "text", text: "/clear" }],
      });

      expect(lastQueryCall.options?.permissionMode).toBe(mode);
      expect(session.queryOptions.permissionMode).toBe(mode);
    },
  );

  it("deletes the stale local jsonl for the stable ACP id after a successful clear", async () => {
    // A cold reconnect hydrates by the stable ACP id (clients never learn the
    // internal SDK id). If the SDK's original file under that id survived a
    // /clear, a future hydration would find it, skip re-fetching the
    // authoritative log, and resume the pre-clear conversation.
    const unlinkSpy = vi
      .spyOn(fs.promises, "unlink")
      .mockResolvedValue(undefined);
    const { agent } = makeAgent();
    installFakeSession(agent, "s-stale");

    await agent.prompt({
      sessionId: "s-stale",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(unlinkSpy).toHaveBeenCalledWith(
      getSessionJsonlPath("s-stale", "/tmp/repo"),
    );
    unlinkSpy.mockRestore();
  });

  it("fails the clear when the stale jsonl survives for a reason other than a missing file", async () => {
    // The file outliving the clear means a cold reconnect hydrates by the stable ACP
    // id, finds it, and restores the pre-clear conversation. Reporting success here
    // would hand back the context the user asked to drop, silently.
    const unlinkSpy = vi
      .spyOn(fs.promises, "unlink")
      .mockRejectedValue(
        Object.assign(new Error("EACCES"), { code: "EACCES" }),
      );
    const { agent, client } = makeAgent();
    installFakeSession(agent, "s-unlink-fails");

    await expect(
      agent.prompt({
        sessionId: "s-unlink-fails",
        prompt: [{ type: "text", text: "/clear" }],
      }),
    ).rejects.toThrow("EACCES");

    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
    ).toBeUndefined();
    expect(
      findAllExtNotifications(client, POSTHOG_NOTIFICATIONS.STATUS).at(-1),
    ).toMatchObject({ status: "clearing_failed" });
    unlinkSpy.mockRestore();
  });

  it("emits the marker after the user message so /clear sits before the boundary", async () => {
    const { agent, client } = makeAgent();
    installFakeSession(agent, "s-order");

    let clearedAt = -1;
    let userMessageAt = -1;
    let order = 0;
    client.extNotification.mockImplementation(async (method: string) => {
      if (method === POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED) {
        clearedAt = order++;
      }
    });
    client.sessionUpdate.mockImplementation(
      async (call: { update?: { sessionUpdate?: string } }) => {
        if (call.update?.sessionUpdate === "user_message_chunk") {
          userMessageAt = order++;
        }
      },
    );

    await agent.prompt({
      sessionId: "s-order",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(userMessageAt).toBeGreaterThanOrEqual(0);
    expect(clearedAt).toBeGreaterThan(userMessageAt);
  });

  it.each([
    {
      name: "an active turn",
      setup: (session: ReturnType<typeof installFakeSession>["session"]) => {
        session.activeTurn = { promptUuid: "u-1", settled: false };
      },
    },
    {
      name: "a queued turn",
      setup: (session: ReturnType<typeof installFakeSession>["session"]) => {
        session.turnQueue.push({ promptUuid: "u-2" });
      },
    },
  ])("refuses to clear while $name is in flight", async ({ setup }) => {
    const { agent, client } = makeAgent();
    const { session, oldQuery } = installFakeSession(agent, "s-busy");
    setup(session);

    const result = await agent.prompt({
      sessionId: "s-busy",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(result.stopReason).toBe("end_turn");
    expect(oldQuery.interrupt).not.toHaveBeenCalled();
    expect(createdQueries).toHaveLength(0);
    const chunk = findUpdate(client, "agent_message_chunk");
    expect((chunk?.content as { text?: string })?.text).toMatch(
      /Cannot clear the conversation/,
    );
    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
    ).toBeUndefined();
  });

  it("refuses a second /clear while one is already in progress", async () => {
    // ACP handlers are not serialized, so a second /clear can arrive at any
    // await point of the first. Racing two swaps against the same session
    // would orphan a live SDK query; the second must be refused.
    const { agent, client } = makeAgent();
    installFakeSession(agent, "s-concurrent");
    const init = deferInit();

    const first = agent.prompt({
      sessionId: "s-concurrent",
      prompt: [{ type: "text", text: "/clear" }],
    });
    // Let the first clear reach its init await (one replacement query live).
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    const second = await agent.prompt({
      sessionId: "s-concurrent",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(second.stopReason).toBe("end_turn");
    const chunk = findUpdate(client, "agent_message_chunk");
    expect((chunk?.content as { text?: string })?.text).toMatch(
      /already in progress/,
    );
    // The refused clear started no second swap.
    expect(createdQueries).toHaveLength(1);

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(first).resolves.toMatchObject({ stopReason: "end_turn" });
    expect(
      findAllExtNotifications(
        client,
        POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED,
      ),
    ).toHaveLength(1);
  });

  it("ignores a cancel that arrives while a clear is in progress", async () => {
    // cancel() → interrupt() targets session.query, which mid-clear is the
    // half-initialized replacement; interrupting it would corrupt the swap.
    const { agent, client } = makeAgent();
    installFakeSession(agent, "s-cancel-mid-clear");
    const init = deferInit();

    const clearPromise = agent.prompt({
      sessionId: "s-cancel-mid-clear",
      prompt: [{ type: "text", text: "/clear" }],
    });
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    await agent.cancel({ sessionId: "s-cancel-mid-clear" });
    expect(createdQueries[0].interrupt).not.toHaveBeenCalled();

    init.resolve({ result: "success", commands: [], models: [] });
    await expect(clearPromise).resolves.toMatchObject({
      stopReason: "end_turn",
    });
    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
    ).toBeDefined();
  });

  it("closes the session and reports clearing_failed when the fresh session fails to initialize", async () => {
    // A non-timeout failure (SDK subprocess crash) must get the same
    // treatment as a timeout: terminate the unproven replacement, close the
    // session, and resolve the "Clearing…" spinner as failed — never leave
    // it spinning with the session half-swapped.
    const { agent, client } = makeAgent();
    const { session } = installFakeSession(agent, "s-init-crash");
    const init = deferInit();

    const promptPromise = agent.prompt({
      sessionId: "s-init-crash",
      prompt: [{ type: "text", text: "/clear" }],
    });
    const rejection = expect(promptPromise).rejects.toThrow(
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
    // No trace of the /clear in the log, and the spinner resolves as failed.
    expect(findUpdate(client, "user_message_chunk")).toBeUndefined();
    expect(
      findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
    ).toBeUndefined();
    expect(
      findAllExtNotifications(client, POSTHOG_NOTIFICATIONS.STATUS),
    ).toEqual([
      { sessionId: "s-init-crash", status: "clearing" },
      {
        sessionId: "s-init-crash",
        status: "clearing_failed",
        error: "SDK subprocess crashed",
      },
    ]);
  });

  it("rejects a prompt that arrives mid-clear once the clear fails", async () => {
    // A prompt racing the swap waits for the clear to settle instead of
    // pushing into the retired input stream; a failed clear then surfaces
    // as the usual session-ended rejection.
    const { agent } = makeAgent();
    installFakeSession(agent, "s-prompt-mid-clear");
    const init = deferInit();

    const clearPromise = agent.prompt({
      sessionId: "s-prompt-mid-clear",
      prompt: [{ type: "text", text: "/clear" }],
    });
    await vi.waitFor(() => expect(createdQueries).toHaveLength(1));

    const followUp = agent.prompt({
      sessionId: "s-prompt-mid-clear",
      prompt: [{ type: "text", text: "hello" }],
    });

    const clearRejection = expect(clearPromise).rejects.toThrow(
      /SDK subprocess crashed/,
    );
    const followUpRejection =
      expect(followUp).rejects.toThrow(/session has ended/);
    init.reject(new Error("SDK subprocess crashed"));
    await clearRejection;
    await followUpRejection;
  });

  it("rejects /clear after the session has ended", async () => {
    const { agent } = makeAgent();
    const { session } = installFakeSession(agent, "s-ended");
    (session as unknown as { queryClosed: boolean }).queryClosed = true;

    await expect(
      agent.prompt({
        sessionId: "s-ended",
        prompt: [{ type: "text", text: "/clear" }],
      }),
    ).rejects.toThrow(/session has ended/);
    expect(createdQueries).toHaveLength(0);
  });

  it("refreshSession resumes the post-clear SDK session", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-refresh");

    await agent.prompt({
      sessionId: "s-refresh",
      prompt: [{ type: "text", text: "/clear" }],
    });
    const newSessionId = lastQueryCall.options?.sessionId as string;

    await agent.extMethod(POSTHOG_METHODS.REFRESH_SESSION, {
      mcpServers: [
        { name: "posthog", type: "http" as const, url: "https://fresh" },
      ],
    });

    expect(lastQueryCall.options?.resume).toBe(newSessionId);
    expect(lastQueryCall.options?.sessionId).toBeUndefined();
  });

  it("times out, closes the query, and never logs the /clear prompt if the fresh session never finishes initializing", async () => {
    vi.useFakeTimers();
    try {
      const { agent, client } = makeAgent();
      const { session } = installFakeSession(agent, "s-timeout");
      nextInitPromise = new Promise<InitResult>(() => {
        // Never resolves, forcing the initializationResult() race to time out.
      });

      const promptPromise = agent.prompt({
        sessionId: "s-timeout",
        prompt: [{ type: "text", text: "/clear" }],
      });
      const rejection = expect(promptPromise).rejects.toThrow(/timed out/);

      // Matches the module-private SESSION_VALIDATION_TIMEOUT_MS in claude-agent.ts.
      await vi.advanceTimersByTimeAsync(30_000);
      await rejection;

      expect((session as unknown as { queryClosed: boolean }).queryClosed).toBe(
        true,
      );
      // The /clear prompt is only broadcast (and thus logged) once the new
      // session is confirmed live, so a timeout must leave no trace of it.
      expect(findUpdate(client, "user_message_chunk")).toBeUndefined();
      expect(
        findExtNotification(client, POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED),
      ).toBeUndefined();
      // The "clearing" spinner opened, then the failure closes it out.
      expect(
        findAllExtNotifications(client, POSTHOG_NOTIFICATIONS.STATUS),
      ).toEqual([
        { sessionId: "s-timeout", status: "clearing" },
        {
          sessionId: "s-timeout",
          status: "clearing_failed",
          error: "Conversation clear timed out after 30000ms",
        },
      ]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("resumeSession after /clear echoes the canonical ACP id when matched via the new SDK id", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-reconnect");

    await agent.prompt({
      sessionId: "s-reconnect",
      prompt: [{ type: "text", text: "/clear" }],
    });
    const newSessionId = lastQueryCall.options?.sessionId as string;

    const response = await agent.resumeSession({
      sessionId: newSessionId,
      cwd: "/tmp/repo",
    });

    expect((response as unknown as { sessionId: string }).sessionId).toBe(
      "s-reconnect",
    );
  });

  it("resets pre-clear plan and notification state so it can't resurface after /clear", async () => {
    const { agent } = makeAgent();
    const { session } = installFakeSession(agent, "s-plan");
    (session as unknown as { lastPlanFilePath?: string }).lastPlanFilePath =
      "/tmp/repo/.claude/plans/old.md";
    session.notificationHistory.push({ type: "assistant", text: "old" });
    agent.fileContentCache["/tmp/repo/.claude/plans/old.md"] = "stale content";

    await agent.prompt({
      sessionId: "s-plan",
      prompt: [{ type: "text", text: "/clear" }],
    });

    expect(
      (session as unknown as { lastPlanFilePath?: string }).lastPlanFilePath,
    ).toBeUndefined();
    // The reset happens before broadcastUserMessage, which legitimately logs
    // the "/clear" command itself afterward — assert the stale pre-clear
    // entry is gone rather than the history being empty.
    expect(session.notificationHistory).not.toContainEqual({
      type: "assistant",
      text: "old",
    });
    expect(agent.fileContentCache).toEqual({});
  });
});
