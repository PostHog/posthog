import { type SetupServerApi, setupServer } from "msw/node";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { classifyAgentError } from "../adapters/error-classification";
import type { PostHogAPIClient } from "../posthog-api";
import { createTestRepo, type TestRepo } from "../test/fixtures/api";
import { createPostHogHandlers } from "../test/mocks/msw-handlers";
import type { Task, TaskRun } from "../types";
import { AgentServer, UPSTREAM_PROVIDER_FAILURE_MESSAGE } from "./agent-server";

interface TestableAgentServer {
  posthogAPI: PostHogAPIClient;
  isQuestionMeta: (value: unknown) => boolean;
  getFirstQuestionMeta: (meta: unknown) => unknown;
  relaySlackQuestion: (payload: Record<string, unknown>, meta: unknown) => void;
  createCloudClient: (payload: Record<string, unknown>) => {
    requestPermission: (opts: {
      options: unknown[];
      toolCall: unknown;
    }) => Promise<{
      outcome: { outcome: string; optionId?: string };
      _meta?: { message?: string; answers?: Record<string, string> };
    }>;
  };
  questionRelayedToSlack: boolean;
  session: unknown;
  relayAgentResponse: (
    payload: Record<string, unknown>,
    messageId?: string,
  ) => Promise<void>;
  sendInitialTaskMessage: (payload: Record<string, unknown>) => Promise<void>;
}

const TEST_PAYLOAD = {
  run_id: "test-run-id",
  task_id: "test-task-id",
  team_id: 1,
  user_id: 1,
  distinct_id: "test-distinct-id",
  mode: "interactive" as const,
};

const QUESTION_META = {
  codeToolKind: "question",
  questions: [
    {
      question: "Which license should I use?",
      options: [
        { label: "MIT", description: "Permissive license" },
        { label: "Apache 2.0", description: "Patent grant included" },
        { label: "GPL v3", description: "Copyleft license" },
      ],
    },
  ],
};

function createTransientPromptError(): Error & {
  data: { classification: string; result: string };
} {
  const error = new Error("API Error: terminated") as Error & {
    data: { classification: string; result: string };
  };
  error.data = {
    classification: "upstream_stream_terminated",
    result: "API Error: terminated",
  };
  return error;
}

function createTransientConnectionError(): Error & {
  data: { classification: string; result: string };
} {
  const error = new Error("fetch failed") as Error & {
    data: { classification: string; result: string };
  };
  error.data = {
    classification: "upstream_connection_error",
    result: "fetch failed",
  };
  return error;
}

function createUpstreamProviderFailureError(): Error & {
  data: { classification: string; result: string };
} {
  const result =
    'API Error: 529 {"error":{"message":"{\\"type\\":\\"error\\",\\"error\\":{\\"type\\":\\"overloaded_error\\",\\"message\\":\\"Overloaded\\"}}","type":"api_error"}}';
  const error = new Error(result) as Error & {
    data: { classification: string; result: string };
  };
  error.data = {
    classification: "upstream_provider_failure",
    result,
  };
  return error;
}

describe("Question relay", () => {
  it.each([
    ["API Error: terminated", "upstream_stream_terminated"],
    ["API Error: Connection error", "upstream_connection_error"],
    ["API Error: The operation timed out.", "upstream_timeout"],
    ["API Error: Request timed out.", "upstream_timeout"],
    ["API Error: 429 rate_limit_error", "upstream_provider_failure"],
    ["API Error: 529 overloaded_error", "upstream_provider_failure"],
    ["API Error: 503 internal_error", "upstream_provider_failure"],
    ["something else", "agent_error"],
    [undefined, "agent_error"],
  ])("classifies %p as %s", (message, expected) => {
    expect(classifyAgentError(message)).toBe(expected);
  });

  let repo: TestRepo;
  let server: TestableAgentServer;
  let mswServer: SetupServerApi;
  const port = 3098;

  beforeEach(async () => {
    repo = await createTestRepo("question-relay");
    mswServer = setupServer(
      ...createPostHogHandlers({ baseUrl: "http://localhost:8000" }),
    );
    mswServer.listen({ onUnhandledRequest: "bypass" });

    server = new AgentServer({
      port,
      jwtPublicKey: "unused-in-unit-tests",
      repositoryPath: repo.path,
      apiUrl: "http://localhost:8000",
      apiKey: "test-api-key",
      projectId: 1,
      mode: "interactive",
      taskId: "test-task-id",
      runId: "test-run-id",
    }) as unknown as TestableAgentServer;
  });

  afterEach(async () => {
    mswServer.close();
    await repo.cleanup();
  });

  describe("isQuestionMeta", () => {
    it.each([
      ["null", null],
      ["undefined", undefined],
      ["number", 42],
      ["string", "not a question"],
      ["object without question field", { options: [] }],
      ["object with non-string question", { question: 123 }],
      ["object with non-array options", { question: "Q?", options: "bad" }],
      [
        "object with invalid option items",
        { question: "Q?", options: [{ notLabel: "x" }] },
      ],
    ])("rejects %s", (_label, value) => {
      expect(server.isQuestionMeta(value)).toBe(false);
    });

    it.each([
      [
        "question with options",
        {
          question: "Pick one",
          options: [{ label: "A", description: "desc" }, { label: "B" }],
        },
      ],
      ["question without options", { question: "What do you think?" }],
      ["question with empty options", { question: "Confirm?", options: [] }],
    ])("accepts %s", (_label, value) => {
      expect(server.isQuestionMeta(value)).toBe(true);
    });
  });

  describe("getFirstQuestionMeta", () => {
    it.each([
      ["null meta", null],
      ["undefined meta", undefined],
      ["meta without questions", { other: "field" }],
      ["meta with empty questions array", { questions: [] }],
      ["meta with non-array questions", { questions: "not-array" }],
    ])("returns null for %s", (_label, meta) => {
      expect(server.getFirstQuestionMeta(meta)).toBeNull();
    });

    it("returns first question from valid meta", () => {
      const result = server.getFirstQuestionMeta(QUESTION_META);
      expect(result).toEqual(QUESTION_META.questions[0]);
    });
  });

  describe("relaySlackQuestion", () => {
    it("relays formatted question with options via posthogAPI", () => {
      const relaySpy = vi
        .spyOn(server.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      server.relaySlackQuestion(TEST_PAYLOAD, QUESTION_META);

      expect(relaySpy).toHaveBeenCalledOnce();
      const [taskId, runId, message] = relaySpy.mock.calls[0];
      expect(taskId).toBe("test-task-id");
      expect(runId).toBe("test-run-id");
      expect(message).toContain("*Which license should I use?*");
      expect(message).toContain("1. *MIT*");
      expect(message).toContain("Permissive license");
      expect(message).toContain("2. *Apache 2.0*");
      expect(message).toContain("3. *GPL v3*");
      expect(message).toContain("Reply in this thread");
    });

    it("sets questionRelayedToSlack flag", () => {
      vi.spyOn(server.posthogAPI, "relayMessage").mockResolvedValue(undefined);

      server.relaySlackQuestion(TEST_PAYLOAD, QUESTION_META);
      expect(server.questionRelayedToSlack).toBe(true);
    });

    it("does not relay when meta has no valid question", () => {
      const relaySpy = vi
        .spyOn(server.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      server.relaySlackQuestion(TEST_PAYLOAD, { codeToolKind: "question" });
      expect(server.questionRelayedToSlack).toBe(false);
      expect(relaySpy).not.toHaveBeenCalled();
    });
  });

  describe("createCloudClient requestPermission", () => {
    const ALLOW_OPTIONS = [
      { kind: "allow_once", optionId: "allow", name: "Allow" },
    ];

    describe("with POSTHOG_CODE_INTERACTION_ORIGIN=slack", () => {
      beforeEach(() => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      });

      afterEach(() => {
        delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
      });

      it("returns cancelled with relay message for question tool", async () => {
        vi.spyOn(server.posthogAPI, "relayMessage").mockResolvedValue(
          undefined,
        );
        const client = server.createCloudClient(TEST_PAYLOAD);

        const result = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { _meta: QUESTION_META },
        });

        expect(result.outcome.outcome).toBe("cancelled");
        expect(result._meta?.message).toContain("relayed to the Slack thread");
        expect(result._meta?.message).toContain("Do NOT re-ask the question");
      });

      it("auto-approves non-question tools", async () => {
        const client = server.createCloudClient(TEST_PAYLOAD);

        const result = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { _meta: { codeToolKind: "bash" } },
        });

        expect(result.outcome.outcome).toBe("selected");
      });

      it("auto-approves tools without meta", async () => {
        const client = server.createCloudClient(TEST_PAYLOAD);

        const result = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { _meta: null },
        });

        expect(result.outcome.outcome).toBe("selected");
      });
    });

    describe("without POSTHOG_CODE_INTERACTION_ORIGIN", () => {
      beforeEach(() => {
        delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
      });

      it.each([
        [
          "no client can receive them",
          { eventStreamActive: false, mode: "interactive" },
        ],
        [
          "the run is in background mode even with the event stream active",
          { eventStreamActive: true, mode: "background" },
        ],
      ])("parks question tools when %s", async (_label, config) => {
        const srv = server as TestableAgentServer & {
          eventStreamSender: { enqueue: ReturnType<typeof vi.fn> } | null;
        };
        if (config.eventStreamActive) {
          srv.eventStreamSender = { enqueue: vi.fn() };
        }

        const client = srv.createCloudClient({
          ...TEST_PAYLOAD,
          mode: config.mode,
        });
        const result = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { _meta: QUESTION_META },
        });

        expect(result.outcome.outcome).toBe("cancelled");
        expect(result._meta?.message).toContain(
          "Do NOT pick an answer yourself",
        );
      });

      it("relays question tools when the durable event stream is active", async () => {
        const appendRawLine = vi.fn();
        const enqueue = vi.fn();
        const srv = server as TestableAgentServer & {
          eventStreamSender: { enqueue: typeof enqueue } | null;
          resolvePermission: (
            requestId: string,
            optionId: string,
            customInput?: string,
            answers?: Record<string, string>,
          ) => "resolved" | "not_found" | "invalid_option";
        };
        srv.session = {
          payload: TEST_PAYLOAD,
          sseController: null,
          hasDesktopConnected: false,
          logWriter: { appendRawLine },
        };
        srv.eventStreamSender = { enqueue };

        const client = srv.createCloudClient(TEST_PAYLOAD);
        const pending = client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { toolCallId: "question-1", _meta: QUESTION_META },
        });

        const request = appendRawLine.mock.calls
          .map(([, line]) => JSON.parse(line))
          .find((n) => n?.method === "_posthog/permission_request");
        expect(request).toBeDefined();
        expect(enqueue).toHaveBeenCalledWith(
          expect.objectContaining({ type: "permission_request" }),
        );

        srv.resolvePermission(
          request.params.requestId as string,
          "option_0",
          undefined,
          { "Which license should I use?": "MIT" },
        );

        const result = await pending;
        expect(result.outcome.outcome).toBe("selected");
        expect(result._meta?.answers).toEqual({
          "Which license should I use?": "MIT",
        });
      });

      it("keeps auto-approving permissions after SSE send failures", async () => {
        const appendRawLine = vi.fn();
        const brokenSseController = {
          send: vi.fn(() => {
            throw new Error("stream closed");
          }),
          close: vi.fn(),
        };

        const cloudPermissionServer = server as TestableAgentServer & {
          emitConsoleLog: (
            level: "debug" | "info" | "warn" | "error",
            scope: string,
            message: string,
            data?: unknown,
          ) => void;
          logger: { debug: (message: string, data?: unknown) => void };
          session: {
            payload: typeof TEST_PAYLOAD;
            sseController: typeof brokenSseController | null;
            logWriter: {
              appendRawLine: (runId: string, line: string) => void;
            };
          };
        };

        cloudPermissionServer.session = {
          payload: TEST_PAYLOAD,
          sseController: brokenSseController,
          logWriter: {
            appendRawLine,
          },
        };
        cloudPermissionServer.logger = {
          debug: (message: string, data?: unknown) => {
            cloudPermissionServer.emitConsoleLog(
              "debug",
              "agent",
              message,
              data,
            );
          },
        };

        const client = cloudPermissionServer.createCloudClient(TEST_PAYLOAD);

        const firstResult = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { _meta: { codeToolKind: "bash" } },
        });

        expect(firstResult.outcome.outcome).toBe("selected");
        expect(brokenSseController.send).toHaveBeenCalledTimes(1);
        expect(cloudPermissionServer.session.sseController).toBeNull();

        const secondResult = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: { _meta: { codeToolKind: "bash" } },
        });

        expect(secondResult.outcome.outcome).toBe("selected");
        expect(brokenSseController.send).toHaveBeenCalledTimes(1);
        expect(appendRawLine).toHaveBeenCalledTimes(2);
      });
    });

    describe("with createPr disabled", () => {
      it("cancels publish commands", async () => {
        server = new AgentServer({
          port,
          jwtPublicKey: "unused-in-unit-tests",
          repositoryPath: repo.path,
          apiUrl: "http://localhost:8000",
          apiKey: "test-api-key",
          projectId: 1,
          mode: "interactive",
          taskId: "test-task-id",
          runId: "test-run-id",
          createPr: false,
        }) as unknown as TestableAgentServer;

        const client = server.createCloudClient(TEST_PAYLOAD);
        const result = await client.requestPermission({
          options: ALLOW_OPTIONS,
          toolCall: {
            rawInput: { command: "git push origin my-branch" },
            _meta: { toolName: "Bash" },
          },
        });

        expect(result.outcome.outcome).toBe("cancelled");
        expect(result._meta?.message).toContain("stop before publishing");
      });
    });
  });

  describe("permission lifecycle persisted to log", () => {
    it("persists the request (with requestId) and its resolution", async () => {
      const appendRawLine = vi.fn();
      const srv = server as TestableAgentServer & {
        relayPermissionToClient: (p: {
          options: unknown[];
          toolCall?: unknown;
        }) => Promise<{ outcome: { outcome: string; optionId: string } }>;
        resolvePermission: (
          requestId: string,
          optionId: string,
        ) => "resolved" | "not_found" | "invalid_option";
        session: {
          payload: typeof TEST_PAYLOAD;
          sseController: null;
          logWriter: { appendRawLine: typeof appendRawLine };
        };
      };
      srv.session = {
        payload: TEST_PAYLOAD,
        sseController: null,
        logWriter: { appendRawLine },
      };

      const logged = (method: string) =>
        appendRawLine.mock.calls
          .map(([, line]) => JSON.parse(line))
          .find((n) => n?.method === method);

      const promise = srv.relayPermissionToClient({
        options: [{ kind: "allow_once", optionId: "allow", name: "Allow" }],
        toolCall: { toolCallId: "tool-1", title: "Ready to code?" },
      });

      const request = logged("_posthog/permission_request");
      expect(request).toBeTruthy();
      expect(typeof request.params.requestId).toBe("string");
      expect(request.params.toolCallId).toBe("tool-1");
      const requestId = request.params.requestId;

      expect(srv.resolvePermission(requestId, "allow")).toBe("resolved");

      const resolved = logged("_posthog/permission_resolved");
      expect(resolved).toBeTruthy();
      expect(resolved.params.requestId).toBe(requestId);
      expect(resolved.params.toolCallId).toBe("tool-1");
      expect(resolved.params.optionId).toBe("allow");

      await expect(promise).resolves.toMatchObject({
        outcome: { outcome: "selected", optionId: "allow" },
      });
    });
  });

  describe("relayAgentResponse duplicate suppression", () => {
    it("skips relay when questionRelayedToSlack is set", async () => {
      const relaySpy = vi
        .spyOn(server.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      server.session = {
        payload: TEST_PAYLOAD,
        logWriter: {
          flush: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue("agent response"),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      server.questionRelayedToSlack = true;
      await server.relayAgentResponse(TEST_PAYLOAD);

      expect(server.questionRelayedToSlack).toBe(false);
      expect(relaySpy).not.toHaveBeenCalled();
    });

    it("relays normally when questionRelayedToSlack is not set", async () => {
      const relaySpy = vi
        .spyOn(server.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      server.session = {
        payload: TEST_PAYLOAD,
        logWriter: {
          flush: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue("agent response"),
          getAgentResponseParts: vi
            .fn()
            .mockReturnValue(["first part", "agent response"]),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      server.questionRelayedToSlack = false;
      await server.relayAgentResponse(TEST_PAYLOAD);

      expect(relaySpy).toHaveBeenCalledWith(
        "test-task-id",
        "test-run-id",
        "agent response",
        ["first part", "agent response"],
        undefined,
      );
    });

    it("passes the initiating message id through to relayMessage", async () => {
      const relaySpy = vi
        .spyOn(server.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      server.session = {
        payload: TEST_PAYLOAD,
        logWriter: {
          flush: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue("agent response"),
          getAgentResponseParts: vi.fn().mockReturnValue(["agent response"]),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      server.questionRelayedToSlack = false;
      await server.relayAgentResponse(TEST_PAYLOAD, "msg-123");

      expect(relaySpy).toHaveBeenCalledWith(
        "test-task-id",
        "test-run-id",
        "agent response",
        ["agent response"],
        "msg-123",
      );
    });

    it("does not relay when no agent message is available", async () => {
      const relaySpy = vi
        .spyOn(server.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      server.session = {
        payload: TEST_PAYLOAD,
        logWriter: {
          flush: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      server.questionRelayedToSlack = false;
      await server.relayAgentResponse(TEST_PAYLOAD);

      expect(relaySpy).not.toHaveBeenCalled();
    });
  });

  describe("sendInitialTaskMessage prompt source", () => {
    it("uses pending user prompt blocks when present", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "original task description",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: {
          pending_user_message:
            '__twig_cloud_prompt_v1__:{"blocks":[{"type":"text","text":"read this attachment"},{"type":"resource","resource":{"uri":"attachment://test.txt","text":"hello from file","mimeType":"text/plain"}}]}',
        },
      } as unknown as TaskRun);

      const promptSpy = vi.fn().mockResolvedValue({ stopReason: "max_tokens" });
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      await server.sendInitialTaskMessage(TEST_PAYLOAD);

      expect(promptSpy).toHaveBeenCalledWith({
        sessionId: "acp-session",
        prompt: [
          { type: "text", text: "read this attachment" },
          {
            type: "resource",
            resource: {
              uri: "attachment://test.txt",
              text: "hello from file",
              mimeType: "text/plain",
            },
          },
        ],
      });
    });

    it("uses run state initial_prompt_override when present", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "original task description",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: { initial_prompt_override: "override instruction" },
      } as unknown as TaskRun);

      const promptSpy = vi.fn().mockResolvedValue({ stopReason: "max_tokens" });
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      await server.sendInitialTaskMessage(TEST_PAYLOAD);

      expect(promptSpy).toHaveBeenCalledWith({
        sessionId: "acp-session",
        prompt: [{ type: "text", text: "override instruction" }],
      });
    });

    it("falls back to task description when override is missing", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "original task description",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: {},
      } as unknown as TaskRun);

      const promptSpy = vi.fn().mockResolvedValue({ stopReason: "max_tokens" });
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      await server.sendInitialTaskMessage(TEST_PAYLOAD);

      expect(promptSpy).toHaveBeenCalledWith({
        sessionId: "acp-session",
        prompt: [{ type: "text", text: "original task description" }],
      });
    });

    it("does not build a description prompt for a prewarmed run awaiting its forwarded message", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "/millie readme this skill",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: { prewarmed: true },
      } as unknown as TaskRun);

      const promptSpy = vi.fn().mockResolvedValue({ stopReason: "end_turn" });
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      await server.sendInitialTaskMessage(TEST_PAYLOAD);

      expect(promptSpy).not.toHaveBeenCalled();
    });

    it("replays a transient upstream termination with a continuation prompt", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "original task description",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: {},
      } as unknown as TaskRun);

      const promptSpy = vi
        .fn()
        .mockRejectedValueOnce(createTransientPromptError())
        .mockResolvedValueOnce({ stopReason: "cancelled" });
      const updateTaskRunSpy = vi
        .spyOn(server.posthogAPI, "updateTaskRun")
        .mockResolvedValue({} as TaskRun);
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      vi.useFakeTimers();
      try {
        const sendPromise = server.sendInitialTaskMessage(TEST_PAYLOAD);
        await vi.advanceTimersByTimeAsync(5_000);
        await sendPromise;
      } finally {
        vi.useRealTimers();
      }

      expect(promptSpy).toHaveBeenCalledTimes(2);
      const continuation = promptSpy.mock.calls[1][0] as {
        prompt: Array<{ type: string; text: string }>;
      };
      expect(continuation.prompt[0].text).toContain(
        "interrupted by a transient connection error",
      );
      expect(updateTaskRunSpy).not.toHaveBeenCalled();
    });

    it("re-sends the original prompt after an upstream provider failure", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "original task description",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: {},
      } as unknown as TaskRun);

      const promptSpy = vi
        .fn()
        .mockRejectedValueOnce(createUpstreamProviderFailureError())
        .mockResolvedValueOnce({ stopReason: "cancelled" });
      const updateTaskRunSpy = vi
        .spyOn(server.posthogAPI, "updateTaskRun")
        .mockResolvedValue({} as TaskRun);
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      vi.useFakeTimers();
      try {
        const sendPromise = server.sendInitialTaskMessage(TEST_PAYLOAD);
        await vi.advanceTimersByTimeAsync(5_000);
        await sendPromise;
      } finally {
        vi.useRealTimers();
      }

      expect(promptSpy).toHaveBeenCalledTimes(2);
      const retryRequest = promptSpy.mock.calls[1][0] as {
        prompt: Array<{ type: string; text: string }>;
      };
      expect(retryRequest.prompt[0].text).toBe("original task description");
      expect(updateTaskRunSpy).not.toHaveBeenCalled();
    });

    it("surfaces the shared provider failure message once upstream retries are exhausted", async () => {
      vi.spyOn(server.posthogAPI, "getTask").mockResolvedValue({
        id: "test-task-id",
        title: "t",
        description: "original task description",
      } as unknown as Task);
      vi.spyOn(server.posthogAPI, "getTaskRun").mockResolvedValue({
        id: "test-run-id",
        task: "test-task-id",
        state: {},
      } as unknown as TaskRun);

      const promptSpy = vi.fn().mockImplementation(async () => {
        throw createTransientConnectionError();
      });
      const updateTaskRunSpy = vi
        .spyOn(server.posthogAPI, "updateTaskRun")
        .mockResolvedValue({} as TaskRun);
      server.session = {
        payload: TEST_PAYLOAD,
        acpSessionId: "acp-session",
        clientConnection: { prompt: promptSpy },
        logWriter: {
          flushAll: vi.fn().mockResolvedValue(undefined),
          getFullAgentResponse: vi.fn().mockReturnValue(null),
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flush: vi.fn().mockResolvedValue(undefined),
          isRegistered: vi.fn().mockReturnValue(true),
        },
      };

      vi.useFakeTimers();
      try {
        const sendPromise = server.sendInitialTaskMessage(TEST_PAYLOAD);
        await vi.advanceTimersByTimeAsync(10_000);
        await sendPromise;
      } finally {
        vi.useRealTimers();
      }

      expect(promptSpy).toHaveBeenCalledTimes(3);
      expect(updateTaskRunSpy).toHaveBeenCalledWith(
        "test-task-id",
        "test-run-id",
        {
          status: "failed",
          error_message: UPSTREAM_PROVIDER_FAILURE_MESSAGE,
        },
      );
    });
  });
});
