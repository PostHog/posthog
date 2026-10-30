import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import {
  type SDKMessage,
  type SDKUserMessage,
  query as sdkQuery,
} from "@anthropic-ai/claude-agent-sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createMockQuery,
  createSuccessResult,
  type MockQuery,
} from "../../test/mocks/claude-sdk";
import { Logger } from "../../utils/logger";
import { Pushable } from "../../utils/streams";
import { DEFAULT_MODEL_PRICES, RunBudgetGuard } from "./session/budget-guard";
import { toEffortFlagSettings } from "./session/options";

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(),
}));

vi.mock("./mcp/tool-metadata", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./mcp/tool-metadata")>()),
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

function installHarness(
  sessionId: string,
  budgetGuard?: RunBudgetGuard,
): Harness {
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
    budgetGuard,
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

function budgetGuard(): RunBudgetGuard {
  return new RunBudgetGuard(
    1,
    DEFAULT_MODEL_PRICES,
    new Logger({ debug: false }),
  );
}

function sendCostlyAssistantMessage(
  query: MockQuery,
  id = "m1",
  cacheReadTokens = 2_000_000,
): void {
  query._mockHelpers.sendMessage({
    type: "assistant",
    uuid: `a-${id}`,
    session_id: "s",
    parent_tool_use_id: null,
    message: {
      id,
      role: "assistant",
      model: "claude-opus-5",
      content: [],
      usage: {
        input_tokens: 0,
        output_tokens: 0,
        cache_read_input_tokens: cacheReadTokens,
      },
    },
  } as unknown as SDKMessage);
}

async function runningTurnWithQueuedSecond(
  sessionId: string,
  guard?: RunBudgetGuard,
): Promise<
  Harness & {
    first: Promise<unknown>;
    second: Promise<unknown>;
  }
> {
  const harness = installHarness(sessionId, guard);
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

describe("ClaudeAcpAgent turn queue input dispatch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    {
      name: "resumes the conversation in a rebuilt query",
      liveContextKey: "context-1m-2025-08-07|200000",
      hasTranscript: true,
      backgroundTurnActive: false,
      rebuilt: { resume: "s-context-window" },
    },
    {
      name: "starts a rebuilt query fresh before the first saved turn",
      liveContextKey: "context-1m-2025-08-07|200000",
      hasTranscript: false,
      backgroundTurnActive: false,
      rebuilt: { sessionId: "s-context-window" },
    },
    {
      name: "keeps the query when the context window is unchanged",
      liveContextKey: "context-1m-2025-08-07|",
      hasTranscript: true,
      backgroundTurnActive: false,
      rebuilt: null,
    },
    {
      name: "keeps the query while a background turn runs",
      liveContextKey: "context-1m-2025-08-07|200000",
      hasTranscript: true,
      backgroundTurnActive: true,
      rebuilt: null,
    },
  ])(
    "$name",
    async ({
      liveContextKey,
      hasTranscript,
      backgroundTurnActive,
      rebuilt,
    }) => {
      const sessionId = "s-context-window";
      const harness = installHarness(sessionId);
      const session = (
        harness.agent as unknown as {
          session: {
            modelId: string;
            liveContextKey?: string;
            hasTranscript?: boolean;
            backgroundTurnActive?: boolean;
            effort?: string;
            fastModeEnabled?: boolean;
            queryOptions: Record<string, unknown>;
          };
        }
      ).session;
      session.modelId = "claude-opus-5-5";
      session.liveContextKey = liveContextKey;
      session.hasTranscript = hasTranscript;
      session.backgroundTurnActive = backgroundTurnActive;
      session.effort = "ultracode";
      session.fastModeEnabled = true;
      session.queryOptions.betas = ["context-1m-2025-08-07"];
      session.queryOptions.env = {};
      const rebuiltQuery = createMockQuery();
      vi.mocked(sdkQuery).mockReturnValue(
        rebuiltQuery as unknown as ReturnType<typeof sdkQuery>,
      );

      harness.agent
        .prompt({ sessionId, prompt: [{ type: "text", text: "next" }] })
        .catch(() => undefined);
      await tick();
      await tick();

      if (!rebuilt) {
        expect(vi.mocked(sdkQuery)).not.toHaveBeenCalled();
        expect(harness.pushed).toHaveLength(1);
        return;
      }
      const [{ prompt: rebuiltInput, options }] =
        vi.mocked(sdkQuery).mock.calls[0];
      expect(options).toMatchObject({
        betas: ["context-1m-2025-08-07"],
        ...rebuilt,
      });
      expect("resume" in (options ?? {})).toBe(hasTranscript);
      expect(options?.env?.CLAUDE_CODE_AUTO_COMPACT_WINDOW).toBeUndefined();
      expect(rebuiltQuery.applyFlagSettings).toHaveBeenCalledWith(
        toEffortFlagSettings("ultracode"),
      );
      expect(rebuiltQuery.applyFlagSettings).toHaveBeenCalledWith({
        fastMode: true,
      });
      const sent = await (rebuiltInput as AsyncIterable<SDKUserMessage>)
        [Symbol.asyncIterator]()
        .next();
      expect(JSON.stringify(sent.value?.message.content)).toContain("next");
      expect(harness.pushed).toHaveLength(0);
    },
  );

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

    await expect(steer).resolves.toMatchObject({
      _meta: { steer: false, steerDeclineCause: "compacting" },
    });
    expect(harness.pushed).toHaveLength(1);

    harness.query._mockHelpers.sendMessage(createSuccessResult());
    await tick();
    harness.query._mockHelpers.complete();
    await expect(first).resolves.toBeDefined();
  });

  it("resends a declined budget steer while the turn keeps working", async () => {
    const sessionId = "s-steer-retry";
    const guard = budgetGuard();
    const harness = installHarness(sessionId, guard);
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

    sendCostlyAssistantMessage(harness.query, "m1", 1_100_000);
    await tick();
    await tick();

    expect(guard.snapshot().steers).toMatchObject([
      { stage: "warn", delivered: false },
    ]);
    expect(harness.pushed).toHaveLength(1);

    harness.query._mockHelpers.sendMessage({
      type: "system",
      subtype: "status",
      status: null,
      compact_result: "success",
    } as unknown as SDKMessage);
    await tick();
    sendCostlyAssistantMessage(harness.query, "m2", 100_000);
    await tick();
    await tick();

    expect(harness.pushed).toHaveLength(2);
    expect(JSON.stringify(harness.pushed[1].message.content)).toContain(
      "Budget notice",
    );

    harness.query._mockHelpers.complete();
    await expect(first).resolves.toBeDefined();
  });

  it("leaves a declined budget steer pending during a local-only command", async () => {
    const sessionId = "s-steer-local-command";
    const guard = budgetGuard();
    const harness = installHarness(sessionId, guard);
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
    sendCostlyAssistantMessage(harness.query, "m1", 1_100_000);
    await tick();
    await tick();
    expect(guard.snapshot().steers).toMatchObject([
      { stage: "warn", delivered: false },
    ]);
    harness.query._mockHelpers.sendMessage({
      type: "system",
      subtype: "status",
      status: null,
      compact_result: "success",
    } as unknown as SDKMessage);
    await tick();
    harness.query._mockHelpers.sendMessage(createSuccessResult());
    await tick();
    await expect(first).resolves.toBeDefined();

    const command = harness.agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "/context" }],
    });
    await tick();
    expect(harness.pushed).toHaveLength(2);
    const turnQueue = sessionOf(harness.agent).turnQueue;
    echoTurn(harness.query, turnQueue[turnQueue.length - 1].promptUuid);
    await tick();
    sendCostlyAssistantMessage(harness.query, "m2", 0);
    await tick();
    await tick();

    expect(harness.pushed).toHaveLength(2);
    expect(guard.snapshot().steers).toHaveLength(1);
    expect(guard.takePendingSteer()).toBe("warn");

    harness.query._mockHelpers.sendMessage(createSuccessResult());
    await tick();
    harness.query._mockHelpers.complete();
    await expect(command).resolves.toBeDefined();
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

  it("cancels the running turn and refuses new prompts once the budget is spent", async () => {
    const sessionId = "s-budget-stop";
    const harness = installHarness(sessionId, budgetGuard());
    harness.query.interrupt.mockImplementation(async () => {});
    const first = harness.agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "first" }],
    });
    await tick();
    echoTurn(harness.query, sessionOf(harness.agent).turnQueue[0].promptUuid);
    await tick();

    sendCostlyAssistantMessage(harness.query);
    await tick();
    expect(harness.query.interrupt).toHaveBeenCalledTimes(1);

    await expect(
      harness.agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "keep going" }],
      }),
    ).resolves.toEqual({
      stopReason: "cancelled",
      _meta: { interruptReason: "budget_exhausted" },
    });
    expect(harness.pushed).toHaveLength(1);

    harness.query._mockHelpers.sendMessage({
      type: "system",
      subtype: "session_state_changed",
      state: "idle",
    } as unknown as SDKMessage);
    await expect(first).resolves.toMatchObject({
      stopReason: "cancelled",
      _meta: { interruptReason: "budget_exhausted" },
    });
  });

  it("never sends a prompt queued before the turn that spent the budget", async () => {
    const { query, pushed, first, second } = await runningTurnWithQueuedSecond(
      "s-budget-queued",
      budgetGuard(),
    );

    query._mockHelpers.sendMessage(createSuccessResult({ total_cost_usd: 1 }));
    await tick();

    await expect(second).resolves.toEqual({
      stopReason: "cancelled",
      _meta: { interruptReason: "budget_exhausted" },
    });
    expect(pushed).toHaveLength(1);
    expect(query.interrupt).not.toHaveBeenCalled();
    query._mockHelpers.complete();
    await expect(first).resolves.toMatchObject({ stopReason: "end_turn" });
  });
});
