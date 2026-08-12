import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import type { SDKMessage } from "@anthropic-ai/claude-agent-sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMockQuery, type MockQuery } from "../../test/mocks/claude-sdk";
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
  knownSlashCommands?: Set<string>,
): MockQuery {
  const query = createMockQuery();
  const input = new Pushable();
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
    knownSlashCommands,
  };

  (agent as unknown as { session: typeof session }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return query;
}

function findUnsupportedChunkText(
  calls: ClientMocks["sessionUpdate"]["mock"]["calls"],
): string | undefined {
  const match = calls.find(([call]) => {
    const update = (
      call as {
        update?: { sessionUpdate?: string; content?: { text?: string } };
      }
    ).update;
    return (
      update?.sessionUpdate === "agent_message_chunk" &&
      update?.content?.text?.toLowerCase().includes("unsupported")
    );
  });
  return (match?.[0] as { update: { content: { text: string } } } | undefined)
    ?.update.content.text;
}

describe("ClaudeAcpAgent.prompt — early idle handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const cases = [
    {
      label: "unsupported slash command surfaces error and ends turn",
      sessionId: "s-slash",
      prompt: "/plugin install slack",
      knownCommands: undefined,
      expectsUnsupportedChunk: true,
      commandInMessage: "/plugin",
    },
    {
      label: "non-slash prompt with early idle is silently skipped",
      sessionId: "s-regular",
      prompt: "hello",
      knownCommands: undefined,
      expectsUnsupportedChunk: false,
      commandInMessage: null,
    },
    {
      label:
        "newly installed skill command is refreshed before unsupported check",
      sessionId: "s-new-skill",
      prompt: "/local-test-skill",
      knownCommands: undefined,
      supportedCommandsAfterReload: [
        {
          name: "local-test-skill",
          description: "Local test skill",
          argumentHint: "",
        },
      ],
      expectsUnsupportedChunk: false,
      commandInMessage: null,
    },
    {
      label:
        "known plugin/skill command with early idle is not flagged as unsupported",
      sessionId: "s-skill",
      prompt: "/skills-store use my address pr review skill",
      knownCommands: new Set(["skills-store"]),
      expectsUnsupportedChunk: false,
      commandInMessage: null,
    },
  ] as const;

  it.each(cases)("$label", async (tc) => {
    const { agent, client } = makeAgent();
    const query = installFakeSession(
      agent,
      tc.sessionId,
      tc.knownCommands as Set<string> | undefined,
    );
    if ("supportedCommandsAfterReload" in tc) {
      vi.mocked(query.supportedCommands).mockResolvedValue([
        ...tc.supportedCommandsAfterReload,
      ]);
    }

    const promptPromise = agent.prompt({
      sessionId: tc.sessionId,
      prompt: [{ type: "text", text: tc.prompt }],
    });

    // Let the prompt loop start awaiting the first SDK message.
    await new Promise((resolve) => setImmediate(resolve));

    query._mockHelpers.sendMessage({
      type: "system",
      subtype: "session_state_changed",
      state: "idle",
    } as unknown as SDKMessage);
    query._mockHelpers.complete();

    if (tc.expectsUnsupportedChunk) {
      const result = await promptPromise;
      expect(result.stopReason).toBe("end_turn");

      const text = findUnsupportedChunkText(client.sessionUpdate.mock.calls);
      expect(text).toBeDefined();
      if (tc.commandInMessage) {
        expect(text).toContain(tc.commandInMessage);
      }
    } else {
      // Idle absorbed; the stream then ends before the turn ever starts.
      await expect(promptPromise).rejects.toThrow(/session has ended/);
      expect(
        findUnsupportedChunkText(client.sessionUpdate.mock.calls),
      ).toBeUndefined();
      if ("supportedCommandsAfterReload" in tc) {
        expect(query.reloadSkills).toHaveBeenCalled();
        expect(query.supportedCommands).toHaveBeenCalled();
      }
    }
  });
});

describe("ClaudeAcpAgent.prompt — force-cancel backstop", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function echoQueuedTurn(agent: Agent, query: MockQuery): void {
    const turn = (
      agent as unknown as {
        session: { turnQueue: Array<{ promptUuid: string }> };
      }
    ).session.turnQueue[0];
    query._mockHelpers.sendMessage({
      type: "user",
      uuid: turn.promptUuid,
      session_id: "s",
      parent_tool_use_id: null,
      message: { role: "user", content: "echo" },
    } as unknown as SDKMessage);
  }

  it("returns 'cancelled' when the SDK never yields after interrupt (issue #680)", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-wedged";
    const query = installFakeSession(agent, sessionId);
    query.interrupt.mockImplementation(async () => {});
    (agent as unknown as { forceCancelGraceMs: number }).forceCancelGraceMs = 5;

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "do something slow" }],
    });

    await new Promise((resolve) => setImmediate(resolve));
    // cancel() only arms the backstop for an activated (echoed) turn.
    echoQueuedTurn(agent, query);
    await new Promise((resolve) => setImmediate(resolve));

    await agent.cancel({ sessionId });

    const result = await promptPromise;
    expect(result.stopReason).toBe("cancelled");
  });

  it("clears the backstop timer on a healthy cancel (interrupt yields)", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-healthy";
    const query = installFakeSession(agent, sessionId);
    (agent as unknown as { forceCancelGraceMs: number }).forceCancelGraceMs =
      50_000;

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "do something" }],
    });
    await new Promise((resolve) => setImmediate(resolve));
    echoQueuedTurn(agent, query);
    await new Promise((resolve) => setImmediate(resolve));

    await agent.cancel({ sessionId });

    const result = await promptPromise;
    expect(result.stopReason).toBe("cancelled");
    expect(
      (agent as unknown as { session: { forceCancelTimer?: unknown } }).session
        .forceCancelTimer,
    ).toBeUndefined();
  });

  it("settles a still-queued turn immediately on cancel", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-queued";
    const query = installFakeSession(agent, sessionId);
    query.interrupt.mockImplementation(async () => {});

    const promptPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "never echoed" }],
    });
    await new Promise((resolve) => setImmediate(resolve));

    await agent.cancel({ sessionId });

    const result = await promptPromise;
    expect(result.stopReason).toBe("cancelled");
    const session = (
      agent as unknown as {
        session: { pendingOrphanResults: number; turnQueue: unknown[] };
      }
    ).session;
    expect(session.turnQueue).toHaveLength(0);
    expect(session.pendingOrphanResults).toBe(1);
  });
});
