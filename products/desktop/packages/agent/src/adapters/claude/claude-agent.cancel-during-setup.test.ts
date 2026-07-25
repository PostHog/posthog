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
  getCachedMcpTools: vi.fn().mockReturnValue([]),
  clearMcpToolMetadataCache: vi.fn(),
  setMcpToolApprovalStates: vi.fn(),
  isMcpToolReadOnly: vi.fn().mockReturnValue(false),
  getMcpToolMetadata: vi.fn().mockReturnValue(undefined),
  getMcpToolApprovalState: vi.fn().mockReturnValue(undefined),
}));

const { ClaudeAcpAgent } = await import("./claude-agent");
type Agent = InstanceType<typeof ClaudeAcpAgent>;

const SESSION_ID = "s-cancel";

/** Lets the consumer loop re-park in `query.next()` between messages. */
function tick(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

interface Harness {
  agent: Agent;
  session: { cancelled: boolean; cancelSeq: number };
  /** Resolves once prompt() has entered the pre-prompt MCP status await. */
  inSetup: Promise<void>;
  /** Lets the stalled status check return, so setup continues. */
  finishSetup: () => void;
  /** Drives the queued turn to a normal completion. */
  completeTurn: () => Promise<void>;
  /** Promotes the queued turn the way a local-only command's output does. */
  activateQueuedTurn: () => Promise<void>;
  /** Ends the active turn with the SDK's terminal result. */
  finishTurn: () => void;
  /** Whether anything was handed to the SDK. */
  sdkReceivedMessage: () => boolean;
  /** The text of every message handed to the SDK, in order. */
  sdkPromptTexts: () => string[];
  prompt: (text?: string) => Promise<{ stopReason: string; _meta?: unknown }>;
}

/**
 * A session whose pre-prompt `ensureLocalToolsConnected` can be held open, which
 * is the window a Ctrl-C lands in before the prompt reaches the SDK.
 *
 * `query.interrupt` is a deferred no-op on purpose. In production it asks the
 * Claude subprocess to stop and the message stream keeps running until the
 * subprocess acknowledges; the default mock ends the stream synchronously, so the
 * consumer takes the stream-`done` branch and rejects the still-queued turn as
 * session-ended, never reaching `activateTurn`.
 */
function makeHarness(): Harness {
  const client = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  };
  const agent = new ClaudeAcpAgent(client as unknown as AgentSideConnection);

  const query = createMockQuery();
  query.interrupt = vi.fn(async () => {});
  const input = new Pushable<SDKUserMessage>();
  const pushToSdk = vi.spyOn(input, "push");
  const abortController = new AbortController();

  const session = {
    query,
    queryOptions: { sessionId: SESSION_ID, cwd: "/tmp/repo", abortController },
    // Non-empty, so ensureLocalToolsConnected does not short-circuit.
    localToolsServerNames: ["posthog-code-tools"],
    buildInProcessMcpServers: () => ({
      "posthog-code-tools": {
        type: "sdk",
        name: "posthog-code-tools",
        instance: {},
      },
    }),
    input,
    cancelled: false,
    cancelSeq: 0,
    interruptReason: undefined as string | undefined,
    settingsManager: { dispose: vi.fn(), getRepoRoot: () => "/tmp/repo" },
    permissionMode: "auto" as const,
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
  (agent as unknown as { sessionId: string }).sessionId = SESSION_ID;

  const { promise: inSetup, resolve: signalInSetup } =
    Promise.withResolvers<void>();
  const { promise: held, resolve: releaseSetup } = Promise.withResolvers<[]>();
  query.mcpServerStatus = vi.fn(() => {
    signalInSetup();
    return held;
  }) as unknown as MockQuery["mcpServerStatus"];

  return {
    agent,
    session,
    inSetup,
    finishSetup: () => releaseSetup([]),
    prompt: (text = "do the thing") =>
      agent.prompt({
        sessionId: SESSION_ID,
        prompt: [{ type: "text", text }],
      }) as Promise<{ stopReason: string; _meta?: unknown }>,
    activateQueuedTurn: async () => {
      query._mockHelpers.sendMessage({
        type: "system",
        subtype: "local_command_output",
        content: "context report",
        uuid: crypto.randomUUID(),
        session_id: SESSION_ID,
      } as SDKMessage);
      await tick();
    },
    finishTurn: () => query._mockHelpers.complete(createSuccessResult()),
    // Echo the turn's own user message back, then send the terminal result, the
    // way the SDK would for a turn that ran to completion.
    completeTurn: async () => {
      const { value: pushed } = await input[Symbol.asyncIterator]().next();
      query._mockHelpers.sendMessage(pushed as never);
      await tick();
      query._mockHelpers.complete(createSuccessResult());
    },
    sdkReceivedMessage: () => pushToSdk.mock.calls.length > 0,
    sdkPromptTexts: () =>
      pushToSdk.mock.calls.map(([message]) => {
        const content = message.message.content;
        if (typeof content === "string") {
          return content;
        }
        return content
          .map((block) => (block.type === "text" ? block.text : ""))
          .join("");
      }),
  };
}

/**
 * `cancelSeq` lets `prompt()` tell a cancel aimed at the prompt it is setting up
 * from a stale one that already stopped an earlier turn. The first drops the
 * prompt before it reaches the SDK; the second leaves it alone.
 */
describe("cancel arriving while a prompt is being set up", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("drops the prompt instead of handing it to the SDK", async () => {
    const h = makeHarness();

    const pending = h.prompt();
    await h.inSetup;
    // Ctrl-C lands here: nothing is queued yet, so cancel() finds no turn to stop
    // and arms no backstop. Only the early return in prompt() can honor it.
    await h.agent.cancel({ sessionId: SESSION_ID });
    h.finishSetup();

    await expect(pending).resolves.toMatchObject({ stopReason: "cancelled" });
    expect(h.sdkReceivedMessage()).toBe(false);
    expect(h.session.cancelled).toBe(true);
  });

  it("carries the interrupt reason the cancel supplied", async () => {
    const h = makeHarness();

    const pending = h.prompt();
    await h.inSetup;
    await h.agent.cancel({
      sessionId: SESSION_ID,
      _meta: { interruptReason: "user_stopped" },
    });
    h.finishSetup();

    await expect(pending).resolves.toMatchObject({
      stopReason: "cancelled",
      _meta: { interruptReason: "user_stopped" },
    });
  });

  it("runs the next prompt on the same session normally", async () => {
    const h = makeHarness();

    const cancelled = h.prompt();
    await h.inSetup;
    await h.agent.cancel({ sessionId: SESSION_ID });
    h.finishSetup();
    await expect(cancelled).resolves.toMatchObject({ stopReason: "cancelled" });
    // The flag is left standing so a still-settling earlier turn can read it.
    expect(h.session.cancelled).toBe(true);

    const pending = h.prompt();
    await h.completeTurn();

    await expect(pending).resolves.toMatchObject({ stopReason: "end_turn" });
    expect(h.session.cancelled).toBe(false);
  });

  it("runs a prompt normally when the cancel predates it", async () => {
    const h = makeHarness();

    // Cancel with nothing in flight, which is how a cancel for an
    // already-finished turn looks by the time the next prompt arrives.
    await h.agent.cancel({ sessionId: SESSION_ID });
    expect(h.session.cancelled).toBe(true);

    const pending = h.prompt();
    await h.inSetup;
    h.finishSetup();
    await h.completeTurn();

    await expect(pending).resolves.toMatchObject({ stopReason: "end_turn" });
    expect(h.session.cancelled).toBe(false);
  });

  it("drops the prompt even when a later turn activates during setup", async () => {
    const h = makeHarness();

    const cancelled = h.prompt();
    await h.inSetup;
    await h.agent.cancel({ sessionId: SESSION_ID });

    // A local-only command skips the pre-prompt status check the first prompt is
    // parked in, so it queues and activates while that prompt is still stalled.
    // Activation clears `session.cancelled`, leaving the count as the only record
    // that a cancel landed.
    const local = h.prompt("/context");
    await h.activateQueuedTurn();
    expect(h.session.cancelled).toBe(false);

    h.finishSetup();

    await expect(cancelled).resolves.toMatchObject({ stopReason: "cancelled" });
    expect(h.sdkPromptTexts()).toEqual(["/context"]);

    h.finishTurn();
    await expect(local).resolves.toMatchObject({ stopReason: "end_turn" });
  });

  it("leaves a mismatched cancel uncounted", async () => {
    const h = makeHarness();

    await expect(h.agent.cancel({ sessionId: "other" })).rejects.toThrow(
      /Session ID mismatch/,
    );
    expect(h.session.cancelSeq).toBe(0);
    expect(h.session.cancelled).toBe(false);
  });
});
