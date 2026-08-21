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

function tick(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

async function send(query: MockQuery, message: unknown): Promise<void> {
  query._mockHelpers.sendMessage(message as SDKMessage);
  await tick();
}

// Replays the prompt's own user message back through the query so the
// terminal `result` message is recognized as belonging to the tracked turn.
async function echoUserMessage(
  query: MockQuery,
  input: Pushable<SDKUserMessage>,
): Promise<void> {
  const { value: pushed } = await input[Symbol.asyncIterator]().next();
  await send(query, pushed);
}

function assistantMessage(sessionId: string, apiId: string, text: string) {
  return {
    type: "assistant",
    parent_tool_use_id: null,
    session_id: sessionId,
    uuid: `assistant-${apiId}`,
    message: {
      id: apiId,
      role: "assistant",
      content: [{ type: "text", text }],
    },
  };
}

function resultSuccess(sessionId: string, uuid: string) {
  return {
    type: "result",
    subtype: "success",
    session_id: sessionId,
    uuid,
    result: "",
    is_error: false,
    usage: {},
    modelUsage: {},
  };
}

// Mirrors what the SDK emits when a ScheduleWakeup/Monitor event resumes the
// session outside of a tracked prompt() call.
function taskNotificationUserMessage(sessionId: string, event: string) {
  return {
    type: "user",
    parent_tool_use_id: null,
    session_id: sessionId,
    uuid: `task-notification-${event}`,
    message: {
      role: "user",
      content: `<task-notification>\n<event>${event}</event>\n</task-notification>`,
    },
  };
}

function taskNotificationResult(sessionId: string, uuid: string) {
  return {
    ...resultSuccess(sessionId, uuid),
    origin: { kind: "task-notification" },
  };
}

function extNotificationCalls(
  calls: ClientMocks["extNotification"]["mock"]["calls"],
  method: string,
) {
  return calls.filter(([calledMethod]) => calledMethod === method);
}

describe("ClaudeAcpAgent — task-notification results", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("emits background_turn_complete instead of settling the tracked turn", async () => {
    const { agent, client } = makeAgent();
    const sessionId = "s-task-notification";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "hi" }],
    });
    await tick();
    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_1", "hello"));
    await send(query, resultSuccess(sessionId, "result-1"));
    const result = await promptPromise;
    expect(result.stopReason).toBe("end_turn");

    client.extNotification.mockClear();

    // A ScheduleWakeup/Monitor event resumes the session with no queued
    // turn behind it — this must not settle/reactivate the tracked turn.
    await send(query, taskNotificationUserMessage(sessionId, "ping 1"));
    await send(query, assistantMessage(sessionId, "msg_2", "ping 1 received."));
    await send(query, taskNotificationResult(sessionId, "result-2"));

    expect(
      extNotificationCalls(
        client.extNotification.mock.calls,
        "_posthog/background_turn_complete",
      ),
    ).toEqual([
      [
        "_posthog/background_turn_complete",
        { sessionId, stopReason: "end_turn" },
      ],
    ]);
    expect(
      extNotificationCalls(
        client.extNotification.mock.calls,
        "_posthog/turn_complete",
      ),
    ).toHaveLength(0);
  });

  it("emits background_turn_complete with a refusal stop reason on a task-notification refusal", async () => {
    const { agent, client } = makeAgent();
    const sessionId = "s-task-notification-refusal";
    const { query, input } = installFakeSession(agent, sessionId);

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "hi" }],
    });
    await tick();
    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_1", "hello"));
    await send(query, resultSuccess(sessionId, "result-1"));
    await promptPromise;

    client.extNotification.mockClear();

    await send(query, taskNotificationUserMessage(sessionId, "ping 1"));
    await send(query, {
      ...taskNotificationResult(sessionId, "result-2"),
      stop_reason: "refusal",
    });

    expect(
      extNotificationCalls(
        client.extNotification.mock.calls,
        "_posthog/background_turn_complete",
      ),
    ).toEqual([
      [
        "_posthog/background_turn_complete",
        { sessionId, stopReason: "refusal" },
      ],
    ]);
  });
});
