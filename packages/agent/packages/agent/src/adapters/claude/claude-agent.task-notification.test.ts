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
  waitForSubagents = false,
): { query: MockQuery; input: Pushable<SDKUserMessage> } {
  const query = createMockQuery();
  const input = new Pushable<SDKUserMessage>();
  const abortController = new AbortController();

  const session = {
    query,
    waitForSubagents,
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
      content: `<task-notification>\n<task-id>${event}</task-id>\n</task-notification>`,
    },
    origin: { kind: "task-notification" },
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

  it.each(["completed", "failed", "stopped"])(
    "waits for every sub-agent and the parent's reply when a worker %s",
    async (status) => {
      const { agent, client } = makeAgent();
      const sessionId = "s-pending-subagents";
      const { query, input } = installFakeSession(agent, sessionId, true);
      const settled = vi.fn();
      const prompt = agent
        .prompt({
          sessionId,
          prompt: [{ type: "text", text: "Choose a repository." }],
        })
        .then((result) => {
          settled(result);
          return result;
        });
      await tick();
      await echoUserMessage(query, input);
      for (const taskId of ["worker-a", "worker-b"]) {
        await send(query, {
          type: "system",
          subtype: "task_started",
          task_id: taskId,
          task_type: "local_agent",
          is_backgrounded: true,
        });
      }
      await send(
        query,
        assistantMessage(sessionId, "waiting", "Research is pending."),
      );
      await send(query, {
        ...resultSuccess(sessionId, "initial"),
        usage: { output_tokens: 3 },
      });
      expect(settled).not.toHaveBeenCalled();

      for (const taskId of ["worker-a", "worker-b"]) {
        await send(query, {
          type: "system",
          subtype: "task_notification",
          task_id: taskId,
          status,
          summary: "Worker ended.",
          output_file: "/tmp/worker-output",
        });
        expect(settled).not.toHaveBeenCalled();
        await send(query, taskNotificationUserMessage(sessionId, taskId));
        await send(
          query,
          assistantMessage(
            sessionId,
            taskId,
            taskId === "worker-b"
              ? '{"repository":"example/app"}'
              : "Another worker remains.",
          ),
        );
        await send(query, {
          ...taskNotificationResult(sessionId, taskId),
          usage: { output_tokens: 5 },
        });
        if (taskId === "worker-a") expect(settled).not.toHaveBeenCalled();
      }
      await expect(prompt).resolves.toMatchObject({
        stopReason: "end_turn",
        usage: { outputTokens: 13 },
      });
      expect(
        extNotificationCalls(
          client.extNotification.mock.calls,
          "_posthog/background_turn_complete",
        ),
      ).toHaveLength(0);
      expect(client.sessionUpdate).toHaveBeenCalledWith(
        expect.objectContaining({
          update: expect.objectContaining({
            content: { type: "text", text: '{"repository":"example/app"}' },
          }),
        }),
      );
    },
  );

  it.each(["overlapping", "batched"])(
    "handles %s notifications without accepting an unrelated wakeup",
    async (delivery) => {
      const { agent } = makeAgent();
      const sessionId = "s-subagent-notification-order";
      const { query, input } = installFakeSession(agent, sessionId, true);
      const settled = vi.fn();
      const prompt = agent
        .prompt({ sessionId, prompt: [{ type: "text", text: "Research." }] })
        .then(settled);
      await tick();
      await echoUserMessage(query, input);
      await send(query, {
        type: "system",
        subtype: "background_tasks_changed",
        tasks: ["worker-a", "worker-b"].map((id) => ({
          task_id: id,
          task_type: "local_agent",
          run_id: id,
        })),
      });
      await send(query, {
        type: "system",
        subtype: "task_notification",
        task_id: "worker-a",
        run_id: "worker-a",
        status: "completed",
        summary: "Worker ended.",
      });
      await send(
        query,
        assistantMessage(sessionId, "waiting", "Research is pending."),
      );
      await send(query, resultSuccess(sessionId, "initial"));
      await send(
        query,
        taskNotificationUserMessage(sessionId, "unrelated-wakeup"),
      );
      await send(query, taskNotificationResult(sessionId, "unrelated-result"));
      expect(settled).not.toHaveBeenCalled();

      const workerNotification = (id: string) => ({
        ...taskNotificationUserMessage(sessionId, id),
        origin: { kind: "task-notification", runId: id },
      });
      if (delivery === "overlapping") {
        await send(query, workerNotification("worker-a"));
      }
      await send(query, {
        type: "system",
        subtype: "task_notification",
        task_id: "worker-b",
        run_id: "old-run",
        status: "stopped",
        summary: "Old worker ended.",
      });
      await send(query, {
        type: "system",
        subtype: "task_notification",
        task_id: "worker-b",
        run_id: "worker-b",
        status: "completed",
        summary: "Worker ended.",
      });
      if (delivery === "overlapping") {
        await send(query, workerNotification("worker-b"));
        await send(query, taskNotificationResult(sessionId, "worker-a"));
        expect(settled).not.toHaveBeenCalled();
      } else {
        await send(query, {
          ...taskNotificationUserMessage(sessionId, "batch"),
          message: {
            role: "user",
            content: "<task-id>worker-a</task-id>\n<task-id>worker-b</task-id>",
          },
        });
      }
      await send(
        query,
        assistantMessage(sessionId, "final", "Research complete."),
      );
      await send(query, taskNotificationResult(sessionId, "final"));
      await prompt;
      expect(settled).toHaveBeenCalledOnce();
    },
  );

  it.each([
    ["interactive", false, "local_agent", true, false],
    ["shell", true, "local_bash", true, false],
    ["monitor", true, "local_monitor", true, false],
    ["foreground", true, "local_agent", false, false],
    ["ambient", true, "local_agent", true, true],
  ] as const)(
    "does not wait for %s tasks",
    async (_name, wait, taskType, backgrounded, ambient) => {
      const { agent } = makeAgent();
      const sessionId = "s-independent-task";
      const { query, input } = installFakeSession(agent, sessionId, wait);
      const prompt = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "Proceed." }],
      });
      await tick();
      await echoUserMessage(query, input);
      await send(query, {
        type: "system",
        subtype: "task_started",
        task_id: "worker",
        task_type: taskType,
        is_backgrounded: backgrounded,
        ambient,
      });
      await send(query, assistantMessage(sessionId, "done", "Complete."));
      await send(query, resultSuccess(sessionId, "result"));
      await expect(prompt).resolves.toMatchObject({ stopReason: "end_turn" });
    },
  );

  it.each(["cancel", "stream_end"])(
    "ends a held turn on %s",
    async (ending) => {
      const { agent } = makeAgent();
      const sessionId = "s-subagent-interrupted";
      const { query, input } = installFakeSession(agent, sessionId, true);
      const prompt = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "Research." }],
      });
      await tick();
      await echoUserMessage(query, input);
      await send(query, {
        type: "system",
        subtype: "task_started",
        task_id: "worker",
        task_type: "local_agent",
        is_backgrounded: true,
      });
      await send(
        query,
        assistantMessage(sessionId, "waiting", "Research is pending."),
      );
      await send(query, resultSuccess(sessionId, "initial"));
      if (ending === "cancel") {
        await agent.cancel({ sessionId });
        await expect(prompt).resolves.toMatchObject({
          stopReason: "cancelled",
        });
      } else {
        const rejected = expect(prompt).rejects.toThrow(
          "Session ended before sub-agents returned",
        );
        query._mockHelpers.complete();
        await rejected;
      }
    },
  );

  it("acks a steer sent during a background turn only once the model acts on it", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-task-notification-steer";
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

    await send(query, taskNotificationUserMessage(sessionId, "ping 1"));
    let steerSettled = false;
    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "wrap up now" }],
      _meta: { steer: true },
    });
    void steerPromise.then(() => {
      steerSettled = true;
    });
    await tick();

    await send(query, assistantMessage(sessionId, "msg_2", "ping 1 received."));
    await send(query, taskNotificationResult(sessionId, "result-2"));
    expect(steerSettled).toBe(false);

    await echoUserMessage(query, input);
    expect(steerSettled).toBe(false);
    await send(query, assistantMessage(sessionId, "msg_3", "wrapping up"));
    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: true },
    });
  });

  it("accepts a steer in a background turn whose notification echoed before the previous result", async () => {
    const { agent } = makeAgent();
    const sessionId = "s-task-notification-early-echo";
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

    await send(query, taskNotificationUserMessage(sessionId, "ping 1"));
    await send(query, assistantMessage(sessionId, "msg_2", "ping 1 received."));
    await send(query, taskNotificationUserMessage(sessionId, "ping 2"));
    await send(query, taskNotificationResult(sessionId, "result-2"));
    await send(query, assistantMessage(sessionId, "msg_3", "ping 2 received."));

    const steerPromise = agent.prompt({
      sessionId,
      prompt: [{ type: "text", text: "wrap up now" }],
      _meta: { steer: true },
    });
    await tick();
    await echoUserMessage(query, input);
    await send(query, assistantMessage(sessionId, "msg_4", "wrapping up"));
    await expect(steerPromise).resolves.toMatchObject({
      _meta: { steer: true },
    });
  });

  it("declines a background steer the SDK never echoes after the background turn ends", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const { agent } = makeAgent();
      const sessionId = "s-task-notification-steer-lost";
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

      await send(query, taskNotificationUserMessage(sessionId, "ping 1"));
      const steerPromise = agent.prompt({
        sessionId,
        prompt: [{ type: "text", text: "wrap up now" }],
        _meta: { steer: true },
      });
      await tick();
      await send(query, taskNotificationResult(sessionId, "result-2"));

      await vi.advanceTimersByTimeAsync(30_000);
      await expect(steerPromise).resolves.toMatchObject({
        _meta: { steer: false, steerDeclineCause: "turn_ended_first" },
      });
    } finally {
      vi.useRealTimers();
    }
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
