import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import type {
  SDKMessage,
  SDKUserMessage,
} from "@anthropic-ai/claude-agent-sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMockQuery, type MockQuery } from "../../test/mocks/claude-sdk";
import { Pushable } from "../../utils/streams";

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(),
}));

vi.mock("./mcp/tool-metadata", () => ({
  fetchMcpToolMetadata: vi.fn().mockResolvedValue(undefined),
  getConnectedMcpServerNames: vi.fn().mockReturnValue([]),
  getCachedMcpTools: vi.fn().mockReturnValue([]),
  clearMcpToolMetadataCache: vi.fn(),
  setMcpToolApprovalStates: vi.fn(),
  isMcpToolReadOnly: vi.fn().mockReturnValue(false),
  getMcpToolMetadata: vi.fn().mockReturnValue(undefined),
  getMcpToolApprovalState: vi.fn().mockReturnValue(undefined),
}));

const { ClaudeAcpAgent } = await import("./claude-agent");
type Agent = InstanceType<typeof ClaudeAcpAgent>;

interface ClientMocks {
  sessionUpdate: ReturnType<typeof vi.fn>;
  extNotification: ReturnType<typeof vi.fn>;
}

function makeAgent(options?: {
  onStructuredOutput?: (output: Record<string, unknown>) => Promise<void>;
}): { agent: Agent; client: ClientMocks } {
  const client: ClientMocks = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  };
  const agent = new ClaudeAcpAgent(
    client as unknown as AgentSideConnection,
    options,
  );
  return { agent, client };
}

function installFakeSession(
  agent: Agent,
  sessionId: string,
): { query: MockQuery; input: Pushable<SDKUserMessage> } {
  const query = createMockQuery();
  const input = new Pushable<SDKUserMessage>();
  const abortController = new AbortController();

  const session = {
    query,
    queryOptions: { sessionId, cwd: "/tmp/repo", abortController },
    buildInProcessMcpServers: () => ({}),
    localToolsServerNames: [] as string[],
    input,
    cancelled: false,
    interruptReason: undefined,
    settingsManager: { dispose: vi.fn(), getRepoRoot: () => "/tmp/repo" },
    permissionMode: "default" as const,
    abortController,
    accumulatedUsage: {
      inputTokens: 0,
      outputTokens: 0,
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
    notificationHistory: [] as unknown[],
    taskRunId: "run-1",
    lastContextWindowSize: 200_000,
    modelId: "claude-sonnet-4-6",
    taskState: new Map(),
  };

  (agent as unknown as { session: typeof session }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return { query, input };
}

// Mark the session as having an enabled (but currently disconnected) in-process
// signed-commit server so the pre-prompt heal has something to reconnect.
function enableSignedCommitServer(agent: Agent): void {
  const session = (
    agent as unknown as {
      session: {
        buildInProcessMcpServers: () => Record<string, unknown>;
        localToolsServerNames: string[];
      };
    }
  ).session;
  session.localToolsServerNames = ["posthog-code-tools"];
  session.buildInProcessMcpServers = () => ({
    "posthog-code-tools": {
      type: "sdk",
      name: "posthog-code-tools",
      instance: {},
    },
  });
}

function tick(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

async function send(query: MockQuery, message: unknown): Promise<void> {
  query._mockHelpers.sendMessage(message as SDKMessage);
  await tick();
}

// Replays the prompt's own user message back through the query so
// `promptReplayed` flips and the terminal `result` message is not skipped as a
// background-task result.
async function echoUserMessage(
  query: MockQuery,
  input: Pushable<SDKUserMessage>,
): Promise<void> {
  const { value: pushed } = await input[Symbol.asyncIterator]().next();
  await send(query, pushed);
}

function messageStart(sessionId: string, apiId: string) {
  return {
    type: "stream_event",
    parent_tool_use_id: null,
    session_id: sessionId,
    uuid: `start-${apiId}`,
    event: { type: "message_start", message: { id: apiId, usage: {} } },
  };
}

function textDelta(sessionId: string, text: string) {
  return {
    type: "stream_event",
    parent_tool_use_id: null,
    session_id: sessionId,
    uuid: `delta-${text}`,
    event: {
      type: "content_block_delta",
      index: 0,
      delta: { type: "text_delta", text },
    },
  };
}

function assistantMessage(
  sessionId: string,
  apiId: string,
  text: string,
  usage?: {
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens: number;
    cache_creation_input_tokens: number;
  },
) {
  return {
    type: "assistant",
    parent_tool_use_id: null,
    session_id: sessionId,
    uuid: `assistant-${apiId}`,
    message: {
      id: apiId,
      role: "assistant",
      content: [{ type: "text", text }],
      ...(usage ? { usage } : {}),
    },
  };
}

function resultStructured(
  sessionId: string,
  structured: Record<string, unknown>,
) {
  return { ...resultSuccess(sessionId), structured_output: structured };
}

function subagentMessage(sessionId: string, apiId: string, text: string) {
  return {
    ...assistantMessage(sessionId, apiId, text),
    parent_tool_use_id: "toolu_subagent",
  };
}

function resultError(sessionId: string) {
  return {
    type: "result",
    subtype: "error_during_execution",
    session_id: sessionId,
    uuid: "result-err",
    is_error: true,
    errors: ["boom"],
    usage: {},
    modelUsage: {},
  };
}

function compactBoundary(sessionId: string) {
  return {
    type: "system",
    subtype: "compact_boundary",
    session_id: sessionId,
    uuid: "compact-1",
    compact_metadata: {
      trigger: "auto",
      pre_tokens: 434_000,
    },
  };
}

function resultSuccess(sessionId: string) {
  return {
    type: "result",
    subtype: "success",
    session_id: sessionId,
    uuid: "result-1",
    result: "",
    is_error: false,
    usage: {},
    modelUsage: {},
  };
}

function messageChunkTexts(
  calls: ClientMocks["sessionUpdate"]["mock"]["calls"],
): string[] {
  return calls
    .map(
      ([call]) =>
        (
          call as {
            update?: { sessionUpdate?: string; content?: { text?: string } };
          }
        ).update,
    )
    .filter((update) => update?.sessionUpdate === "agent_message_chunk")
    .map((update) => update?.content?.text ?? "");
}

function usageUpdates(
  calls: ClientMocks["sessionUpdate"]["mock"]["calls"],
): Array<{ used: number; size: number }> {
  return calls.flatMap(([call]) => {
    const update = (
      call as {
        update?: { sessionUpdate?: string; used?: number; size?: number };
      }
    ).update;
    return update?.sessionUpdate === "usage_update" &&
      typeof update.used === "number" &&
      typeof update.size === "number"
      ? [{ used: update.used, size: update.size }]
      : [];
  });
}

describe("ClaudeAcpAgent.prompt — streamed assistant text wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("emits streamed text once and drops the assembled duplicate", async () => {
    const { agent, client } = makeAgent();
    const sessionId = "s-streamed";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "hi" }],
    });
    await tick();

    await echoUserMessage(query, input);
    await send(query, messageStart(sessionId, "msg_1"));
    await send(query, textDelta(sessionId, "hello"));
    await send(query, assistantMessage(sessionId, "msg_1", "hello"));
    await send(query, resultSuccess(sessionId));

    const result = await promptPromise;
    expect(result.stopReason).toBe("end_turn");
    expect(messageChunkTexts(client.sessionUpdate.mock.calls)).toEqual([
      "hello",
    ]);
  });

  it("forwards assembled text when no deltas streamed (gateway path)", async () => {
    const { agent, client } = makeAgent();
    const sessionId = "s-gateway";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "hi" }],
    });
    await tick();

    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_2", "gateway answer"));
    await send(query, resultSuccess(sessionId));

    const result = await promptPromise;
    expect(result.stopReason).toBe("end_turn");
    expect(messageChunkTexts(client.sessionUpdate.mock.calls)).toEqual([
      "gateway answer",
    ]);
  });

  it("does not replace known context usage with incomplete gateway snapshots", async () => {
    const { agent, client } = makeAgent();
    const sessionId = "s-context-usage";
    const { query, input } = installFakeSession(agent, sessionId);
    const session = (
      agent as unknown as {
        session: { contextUsed?: number; lastContextWindowSize?: number };
      }
    ).session;
    session.contextUsed = 434_000;
    session.lastContextWindowSize = 1_000_000;
    vi.mocked(query.getContextUsage).mockRejectedValue(
      new Error("context usage unavailable"),
    );

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "continue" }],
    });
    await tick();

    await echoUserMessage(query, input);
    await send(query, messageStart(sessionId, "msg-context"));
    await send(query, compactBoundary(sessionId));
    await send(
      query,
      assistantMessage(sessionId, "msg-context", "done", {
        input_tokens: 440_000,
        output_tokens: 100,
        cache_read_input_tokens: 0,
        cache_creation_input_tokens: 0,
      }),
    );
    await send(query, resultSuccess(sessionId));
    await promptPromise;

    const updates = usageUpdates(client.sessionUpdate.mock.calls);
    expect(updates.length).toBeGreaterThan(0);
    expect(updates.every(({ used }) => used >= 434_000)).toBe(true);
    expect(updates.every(({ size }) => size === 1_000_000)).toBe(true);
  });

  it("keeps the original turn open until a pending steer is consumed", async () => {
    const { agent, client } = makeAgent();
    const sessionId = "s-steer-ordering";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use orange" }],
    });
    let promptSettled = false;
    void promptPromise.then(() => {
      promptSettled = true;
    });
    await tick();
    await echoUserMessage(query, input);

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use green instead" }],
      _meta: { steer: true },
    });
    await tick();

    await send(query, assistantMessage(sessionId, "msg_orange", "ORANGE"));
    await send(query, resultSuccess(sessionId));
    expect(promptSettled).toBe(false);

    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_green", "GREEN"));
    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: true },
    });
    await send(query, resultSuccess(sessionId));

    await expect(promptPromise).resolves.toMatchObject({
      stopReason: "end_turn",
    });
    expect(messageChunkTexts(client.sessionUpdate.mock.calls)).toEqual([
      "ORANGE",
      "GREEN",
    ]);
  });

  it("keeps the turn open when the steered work outlasts the delivery grace", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const { agent } = makeAgent();
      const sessionId = "s-steer-slow-work";
      const { query, input } = installFakeSession(agent, sessionId);

      const promptPromise = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "use orange" }],
      });
      let promptSettled = false;
      void promptPromise.then(() => {
        promptSettled = true;
      });
      await tick();
      await echoUserMessage(query, input);

      const steerPromise = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "use green instead" }],
        _meta: { steer: true },
      });
      await tick();

      await send(query, resultSuccess(sessionId));
      await echoUserMessage(query, input);
      await send(query, assistantMessage(sessionId, "msg_green", "GREEN"));
      await expect(steerPromise).resolves.toMatchObject({
        _meta: { steer: true },
      });

      await vi.advanceTimersByTimeAsync(60_000);
      expect(promptSettled).toBe(false);

      await send(query, resultSuccess(sessionId));
      await expect(promptPromise).resolves.toMatchObject({
        stopReason: "end_turn",
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("declines a steer the turn ends without acting on", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-steer-unacted";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use orange" }],
    });
    await tick();
    await echoUserMessage(query, input);

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use green instead" }],
      _meta: { steer: true },
    });
    await tick();

    await send(query, assistantMessage(sessionId, "msg_orange", "ORANGE"));
    await send(query, resultSuccess(sessionId));

    // The SDK folds the steer in only as the turn wraps up, so no model output
    // ever follows it.
    await echoUserMessage(query, input);
    await send(query, resultSuccess(sessionId));

    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: false },
    });
    await expect(promptPromise).resolves.toMatchObject({
      stopReason: "end_turn",
    });
  });

  it("delivers structured output from a result that defers on a steer", async () => {
    const onStructuredOutput = vi.fn().mockResolvedValue(undefined);
    const { agent } = makeAgent({ onStructuredOutput });
    const sessionId = "s-steer-structured";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use orange" }],
    });
    await tick();
    await echoUserMessage(query, input);

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use green instead" }],
      _meta: { steer: true },
    });
    await tick();

    // Deferring settlement must not skip the result's own side effects.
    await send(query, resultStructured(sessionId, { answer: 42 }));
    expect(onStructuredOutput).toHaveBeenCalledWith({ answer: 42 });

    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_green", "GREEN"));
    await send(query, resultSuccess(sessionId));

    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: true },
    });
    await expect(promptPromise).resolves.toMatchObject({
      stopReason: "end_turn",
    });
  });

  it("declines a steer when only subagent output follows its echo", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-steer-subagent";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use orange" }],
    });
    await tick();
    await echoUserMessage(query, input);

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use green instead" }],
      _meta: { steer: true },
    });
    await tick();

    await send(query, resultSuccess(sessionId));
    await echoUserMessage(query, input);
    // A separate model context, so it is no evidence the steer landed.
    await send(query, subagentMessage(sessionId, "msg_sub", "SUBAGENT"));
    await send(query, resultSuccess(sessionId));

    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: false },
    });
    await expect(promptPromise).resolves.toMatchObject({
      stopReason: "end_turn",
    });
  });

  it("declines a steer on a queued turn cancelled before it starts", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-steer-cancelled-queue";
    const { query } = installFakeSession(agent, sessionId);
    query.interrupt.mockImplementation(async () => {});

    // Never echoed, so the turn stays queued rather than becoming active.
    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use orange" }],
    });
    await tick();

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use green instead" }],
      _meta: { steer: true },
    });
    await tick();

    await agent.cancel({ sessionId });

    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: false },
    });
    await expect(promptPromise).resolves.toMatchObject({
      stopReason: "cancelled",
    });
  });

  it("fails the turn on an error result rather than deferring on a steer", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-steer-error";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use orange" }],
    });
    const outcome = promptPromise.then(
      () => "resolved",
      () => "rejected",
    );
    await tick();
    await echoUserMessage(query, input);

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "use green instead" }],
      _meta: { steer: true },
    });
    await tick();

    await send(query, resultError(sessionId));

    await expect(outcome).resolves.toBe("rejected");
    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: false },
    });
  });

  it("settles the turn and declines a steer the SDK never folds in", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const { agent } = makeAgent();
      const sessionId = "s-steer-stuck";
      const { query, input } = installFakeSession(agent, sessionId);

      const promptPromise = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "use orange" }],
      });
      let promptSettled = false;
      void promptPromise.then(() => {
        promptSettled = true;
      });
      await tick();
      await echoUserMessage(query, input);

      const steerPromise = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "use green instead" }],
        _meta: { steer: true },
      });
      await tick();

      await send(query, assistantMessage(sessionId, "msg_orange", "ORANGE"));
      await send(query, resultSuccess(sessionId));
      expect(promptSettled).toBe(false);

      await vi.advanceTimersByTimeAsync(30_000);

      await expect(steerPromise).resolves.toMatchObject({
        _meta: { steer: false },
      });
      await expect(promptPromise).resolves.toMatchObject({
        stopReason: "end_turn",
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("declines an explicit steer after the active turn has ended", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-expired-steer";
    installFakeSession(agent, sessionId);

    await expect(
      agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "too late" }],
        _meta: { steer: true },
      }),
    ).resolves.toMatchObject({ _meta: { steer: false } });

    const session = (agent as unknown as { session: { turnQueue: unknown[] } })
      .session;
    expect(session.turnQueue).toHaveLength(0);
  });

  it("reconnects a disconnected signed-commit server before the turn", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-heal";
    const { query, input } = installFakeSession(agent, sessionId);

    // Signed-commit server is enabled but the live query reports it absent.
    enableSignedCommitServer(agent);
    (query.mcpServerStatus as ReturnType<typeof vi.fn>).mockResolvedValue([
      { name: "posthog-code-tools", status: "failed" },
    ]);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "commit this" }],
    });
    await tick();

    // The pre-prompt heal fired before the model turn began.
    expect(query.mcpServerStatus).toHaveBeenCalled();
    expect(query.setMcpServers).toHaveBeenCalledTimes(1);
    const arg = (query.setMcpServers as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as Record<string, unknown>;
    expect(arg["posthog-code-tools"]).toMatchObject({ type: "sdk" });

    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_h", "done"));
    await send(query, resultSuccess(sessionId));
    const result = await promptPromise;
    expect(result.stopReason).toBe("end_turn");
  });

  it("skips the pre-prompt heal for local-only commands", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-local-only";
    const { query } = installFakeSession(agent, sessionId);

    enableSignedCommitServer(agent);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "/context" }],
    });
    await tick();

    expect(query.mcpServerStatus).not.toHaveBeenCalled();
    expect(query.setMcpServers).not.toHaveBeenCalled();

    await send(query, resultSuccess(sessionId));
    await promptPromise;
  });
});
