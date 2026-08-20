import {
  type AgentSideConnection,
  RequestError,
} from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POSTHOG_METHODS } from "../../acp-extensions";
import { Pushable } from "../../utils/streams";

type SdkMessage =
  | { type: "assistant"; message: { content: unknown[] } }
  | { type: "result"; subtype: string };

/** Messages the next one-shot query() will yield when iterated. */
let nextQueryMessages: SdkMessage[] = [];
/** When set, the next query's iterator blocks on this promise before yielding. */
let nextQueryGate: Promise<void> | null = null;

const lastQueryCall: {
  prompt?: unknown;
  options?: Record<string, unknown>;
} = {};

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(
    (params: { prompt: unknown; options: Record<string, unknown> }) => {
      lastQueryCall.prompt = params.prompt;
      lastQueryCall.options = params.options;
      const messages = nextQueryMessages;
      const gate = nextQueryGate;
      return {
        close: vi.fn(),
        [Symbol.asyncIterator]: async function* () {
          if (gate) await gate;
          yield* messages;
        },
      };
    },
  ),
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
  const abortController = new AbortController();
  const input = new Pushable();
  const oldQuery = { close: vi.fn() };
  const hooks = { PreToolUse: [] };

  const session = {
    query: oldQuery,
    queryOptions: {
      sessionId,
      cwd: "/tmp/repo",
      model: "claude-sonnet-4-6",
      mcpServers: {
        posthog: { type: "http", url: "https://example" },
      },
      abortController,
      hooks,
    },
    input,
    modelId: overrides.modelId,
    cwd: "/tmp/repo",
  } as unknown as Parameters<typeof Object.assign>[0];

  (agent as unknown as { session: unknown }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return { session, oldQuery, input, abortController };
}

function assistantText(text: string): SdkMessage {
  return { type: "assistant", message: { content: [{ type: "text", text }] } };
}

describe("ClaudeAcpAgent.extMethod side_question", () => {
  beforeEach(() => {
    nextQueryMessages = [];
    nextQueryGate = null;
    lastQueryCall.prompt = undefined;
    lastQueryCall.options = undefined;
  });

  it.each<[string, Record<string, unknown>]>([
    ["missing question", {}],
    ["non-string question", { question: 42 }],
    ["blank question", { question: "   " }],
  ])("rejects %s with an invalid-params error", async (_label, params) => {
    const agent = makeAgent();
    installFakeSession(agent, "s-1");

    await expect(
      agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, params),
    ).rejects.toThrow(/non-empty question/);
  });

  it("forks a one-shot tool-less query and returns the answer", async () => {
    const agent = makeAgent();
    const { session, oldQuery, input, abortController } = installFakeSession(
      agent,
      "s-2",
    );
    nextQueryMessages = [
      assistantText("The function "),
      assistantText("parses JSONL."),
      { type: "result", subtype: "success" },
    ];

    const result = await agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, {
      question: "what does it do?",
    });

    expect(result).toEqual({ answer: "The function parses JSONL." });

    // The prompt is the wrapped question, sent as a self-terminating string.
    expect(lastQueryCall.prompt).toContain("<system-reminder>");
    expect(lastQueryCall.prompt).toContain("what does it do?");

    // One-shot fork off the live transcript, toolset removed.
    const options = lastQueryCall.options ?? {};
    expect(options.resume).toBe("s-2");
    expect(options.forkSession).toBe(true);
    expect(options.maxTurns).toBe(1);
    expect(options.tools).toEqual([]);
    expect(options.allowedTools).toEqual([]);
    expect(options.mcpServers).toEqual({});
    expect(options.sessionId).toBeUndefined();
    expect(options.hooks).toBeUndefined();
    // Fresh controller: aborting the one-shot must not poison the session.
    expect(options.abortController).not.toBe(abortController);

    // canUseTool hard-denies anything that slips past the empty toolset.
    const canUseTool = options.canUseTool as () => Promise<{
      behavior: string;
    }>;
    await expect(canUseTool()).resolves.toMatchObject({ behavior: "deny" });

    // The live session is untouched.
    const live = session as {
      query: unknown;
      input: unknown;
      queryOptions: { sessionId: string };
    };
    expect(live.query).toBe(oldQuery);
    expect(live.input).toBe(input);
    expect(live.queryOptions.sessionId).toBe("s-2");
    expect((agent as unknown as { sessionId: string }).sessionId).toBe("s-2");
  });

  it("answers on the live session model, not the creation-time option", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-3", { modelId: "claude-opus-4-8" });
    nextQueryMessages = [
      assistantText("yes"),
      { type: "result", subtype: "success" },
    ];

    await agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, { question: "hm?" });

    expect(lastQueryCall.options?.model).toContain("opus");
  });

  it("surfaces an error result subtype as a RequestError", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-4");
    nextQueryMessages = [{ type: "result", subtype: "error_max_turns" }];

    const promise = agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, {
      question: "hm?",
    });
    await expect(promise).rejects.toBeInstanceOf(RequestError);
    await expect(promise).rejects.toThrow(/error_max_turns/);
  });

  it("rejects when the fork produces no answer text", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-5");
    nextQueryMessages = [{ type: "result", subtype: "success" }];

    await expect(
      agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, { question: "hm?" }),
    ).rejects.toThrow(/no answer/);
  });

  it("allows only one side question at a time", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-6");

    let release: () => void = () => {};
    nextQueryGate = new Promise((resolve) => {
      release = resolve;
    });
    nextQueryMessages = [
      assistantText("first"),
      { type: "result", subtype: "success" },
    ];

    const first = agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, {
      question: "first?",
    });
    await expect(
      agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, { question: "second?" }),
    ).rejects.toThrow(/already in progress/);

    release();
    await expect(first).resolves.toEqual({ answer: "first" });

    // The guard clears once the first completes.
    nextQueryGate = null;
    nextQueryMessages = [
      assistantText("third"),
      { type: "result", subtype: "success" },
    ];
    await expect(
      agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, { question: "third?" }),
    ).resolves.toEqual({ answer: "third" });
  });

  it("wraps SDK failures (e.g. nothing to resume) in a clear RequestError", async () => {
    const agent = makeAgent();
    installFakeSession(agent, "s-7");
    nextQueryGate = Promise.reject(new Error("No conversation found"));
    nextQueryGate.catch(() => {});

    const promise = agent.extMethod(POSTHOG_METHODS.SIDE_QUESTION, {
      question: "too early?",
    });
    await expect(promise).rejects.toBeInstanceOf(RequestError);
    await expect(promise).rejects.toThrow(/No conversation found/);
  });
});
