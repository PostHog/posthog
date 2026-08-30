import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import type {
  SDKMessage,
  SDKUserMessage,
} from "@anthropic-ai/claude-agent-sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMockQuery,
  createSuccessResult,
  type MockQuery,
} from "../../test/mocks/claude-sdk";
import { Pushable } from "../../utils/streams";

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(),
}));

vi.mock("./mcp/tool-metadata", () => ({
  fetchMcpToolMetadata: vi.fn().mockResolvedValue(undefined),
  getConnectedMcpServerNames: vi.fn().mockReturnValue([]),
  setMcpToolApprovalStates: vi.fn(),
  isMcpToolReadOnly: vi.fn().mockReturnValue(false),
  getMcpToolMetadata: vi.fn().mockReturnValue(undefined),
  getMcpToolApprovalState: vi.fn().mockReturnValue(undefined),
}));

const { ClaudeAcpAgent } = await import("./claude-agent");
type Agent = InstanceType<typeof ClaudeAcpAgent>;

interface Harness {
  agent: Agent;
  query: MockQuery;
  pushed: SDKUserMessage[];
}

function installHarness(sessionId: string): Harness {
  const client = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  } as unknown as AgentSideConnection;
  const agent = new ClaudeAcpAgent(client);

  const query = createMockQuery();
  const input = new Pushable<SDKUserMessage>();
  const pushed: SDKUserMessage[] = [];
  const originalPush = input.push.bind(input);
  input.push = (item: SDKUserMessage) => {
    pushed.push(item);
    originalPush(item);
  };
  const abortController = new AbortController();

  const session = {
    query,
    sdkSessionId: sessionId,
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
  };

  (agent as unknown as { session: typeof session }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return { agent, query, pushed };
}

function sessionOf(agent: Agent): {
  turnQueue: Array<{ promptUuid: string }>;
  pendingOrphanResults: number;
} {
  return (
    agent as unknown as {
      session: {
        turnQueue: Array<{ promptUuid: string }>;
        pendingOrphanResults: number;
      };
    }
  ).session;
}

function echoTurn(query: MockQuery, promptUuid: string): void {
  query._mockHelpers.sendMessage({
    type: "user",
    uuid: promptUuid,
    session_id: "s",
    parent_tool_use_id: null,
    message: { role: "user", content: "echo" },
  } as unknown as SDKMessage);
}

function tick(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

async function runningTurnWithQueuedSecond(sessionId: string): Promise<
  Harness & {
    first: Promise<unknown>;
    second: Promise<unknown>;
  }
> {
  const harness = installHarness(sessionId);
  const first = harness.agent.prompt({
    sessionId,
    prompt: [{ type: "text", text: "first" }],
  });
  await tick();
  echoTurn(harness.query, sessionOf(harness.agent).turnQueue[0].promptUuid);
  await tick();
  const second = harness.agent.prompt({
    sessionId,
    prompt: [{ type: "text", text: "second" }],
  });
  await tick();
  return { ...harness, first, second };
}

/** Swap the agent's logger for a recorder so the dispatch-timing debug lines
 *  can be asserted. */
function captureDebugLogs(agent: Agent): Array<[string, unknown]> {
  const entries: Array<[string, unknown]> = [];
  (
    agent as unknown as { logger: { debug: (m: string, d?: unknown) => void } }
  ).logger = {
    debug: (message: string, data?: unknown) => {
      entries.push([message, data]);
    },
    info: () => {},
    warn: () => {},
    error: () => {},
  } as never;
  return entries;
}

function assistantMessage(sessionId: string, text: string): SDKMessage {
  return {
    type: "assistant",
    parent_tool_use_id: null,
    session_id: sessionId,
    uuid: `assistant-${text}`,
    message: {
      id: `api-${text}`,
      role: "assistant",
      content: [{ type: "text", text }],
    },
  } as unknown as SDKMessage;
}

function commandsChanged(): SDKMessage {
  return {
    type: "system",
    subtype: "commands_changed",
    commands: [],
  } as unknown as SDKMessage;
}

function timingEntries(
  entries: Array<[string, unknown]>,
  message: string,
): unknown[] {
  return entries.filter(([m]) => m === message).map(([, data]) => data);
}

describe("ClaudeAcpAgent turn queue input dispatch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("holds a queued prompt out of the SDK input until the running turn settles", async () => {
    const sessionId = "s-serialize";
    const { query, pushed, first, second } =
      await runningTurnWithQueuedSecond(sessionId);

    expect(pushed).toHaveLength(1);

    query._mockHelpers.sendMessage(createSuccessResult());
    await tick();

    expect(pushed).toHaveLength(2);

    query._mockHelpers.complete();
    await expect(first).resolves.toBeDefined();
    await expect(second).rejects.toThrow(/session has ended/);
  });

  it("never hands a steer to the SDK while a compaction is running", async () => {
    const sessionId = "s-steer-compacting";
    const harness = installHarness(sessionId);
    const first = harness.agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "first" }],
    });
    await tick();
    echoTurn(harness.query, sessionOf(harness.agent).turnQueue[0].promptUuid);
    await tick();
    harness.query._mockHelpers.sendMessage({
      type: "system",
      subtype: "status",
      status: "compacting",
    } as unknown as SDKMessage);
    await tick();

    const steer = harness.agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "change direction" }],
      _meta: { steer: true },
    });

    await expect(steer).resolves.toMatchObject({ _meta: { steer: false } });
    expect(harness.pushed).toHaveLength(1);

    harness.query._mockHelpers.sendMessage(createSuccessResult());
    await tick();
    harness.query._mockHelpers.complete();
    await expect(first).resolves.toBeDefined();
  });

  it("never hands a prompt cancelled while queued to the SDK", async () => {
    const sessionId = "s-cancel-queued";
    const { agent, query, pushed, first, second } =
      await runningTurnWithQueuedSecond(sessionId);
    query.interrupt.mockImplementation(async () => {});

    await agent.cancel({ sessionId });

    await expect(second).resolves.toMatchObject({ stopReason: "cancelled" });
    expect(pushed).toHaveLength(1);
    expect(sessionOf(agent).pendingOrphanResults).toBe(0);

    query._mockHelpers.sendMessage({
      type: "system",
      subtype: "session_state_changed",
      state: "idle",
    } as unknown as SDKMessage);
    await expect(first).resolves.toMatchObject({ stopReason: "cancelled" });
    expect(pushed).toHaveLength(1);
  });
  it("times the SDK's first response to a dispatched prompt and names the message that ended the wait", async () => {
    const sessionId = "s-first-sdk-message-timing";
    const harness = installHarness(sessionId);
    const entries = captureDebugLogs(harness.agent);
    void harness.agent
      .prompt({ sessionId, prompt: [{ type: "text", text: "hi" }] })
      .catch(() => {});
    await tick();

    harness.query._mockHelpers.sendMessage(commandsChanged());
    await tick();

    const timings = timingEntries(
      entries,
      "First SDK message after prompt dispatch",
    );
    expect(timings).toHaveLength(1);
    expect(timings[0]).toMatchObject({
      sessionId,
      messageType: "system",
      messageSubtype: "commands_changed",
    });
    expect((timings[0] as { waitMs: number }).waitMs).toBeGreaterThanOrEqual(0);
  });

  it("times the SDK's first response once per turn rather than once per message", async () => {
    const sessionId = "s-first-sdk-message-once";
    const harness = installHarness(sessionId);
    const entries = captureDebugLogs(harness.agent);
    void harness.agent
      .prompt({ sessionId, prompt: [{ type: "text", text: "hi" }] })
      .catch(() => {});
    await tick();

    harness.query._mockHelpers.sendMessage(commandsChanged());
    await tick();
    echoTurn(harness.query, sessionOf(harness.agent).turnQueue[0].promptUuid);
    await tick();
    harness.query._mockHelpers.sendMessage(assistantMessage(sessionId, "one"));
    await tick();

    expect(
      timingEntries(entries, "First SDK message after prompt dispatch"),
    ).toHaveLength(1);
  });

  it("times first model output separately, so pre-model setup and model latency stay distinguishable", async () => {
    const sessionId = "s-first-model-output-timing";
    const harness = installHarness(sessionId);
    const entries = captureDebugLogs(harness.agent);
    void harness.agent
      .prompt({ sessionId, prompt: [{ type: "text", text: "hi" }] })
      .catch(() => {});
    await tick();

    harness.query._mockHelpers.sendMessage(commandsChanged());
    await tick();
    echoTurn(harness.query, sessionOf(harness.agent).turnQueue[0].promptUuid);
    await tick();
    harness.query._mockHelpers.sendMessage(assistantMessage(sessionId, "one"));
    await tick();
    harness.query._mockHelpers.sendMessage(assistantMessage(sessionId, "two"));
    await tick();

    const output = timingEntries(
      entries,
      "First model output after prompt dispatch",
    );
    expect(output).toHaveLength(1);
    const firstMessage = timingEntries(
      entries,
      "First SDK message after prompt dispatch",
    )[0] as { waitMs: number };
    expect((output[0] as { waitMs: number }).waitMs).toBeGreaterThanOrEqual(
      firstMessage.waitMs,
    );
  });
});
