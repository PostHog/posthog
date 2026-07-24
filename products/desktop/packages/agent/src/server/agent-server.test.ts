import { createHash } from "node:crypto";
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readlink,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { Adapter } from "@posthog/shared";
import { zipSync } from "fflate";
import jwt from "jsonwebtoken";
import { type SetupServerApi, setupServer } from "msw/node";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import { getSessionJsonlPath } from "../adapters/claude/session/jsonl-hydration";
import type { PermissionMode } from "../execution-mode";
import type { PostHogAPIClient } from "../posthog-api";
import type { ResumeState } from "../resume";
import {
  createMockApiClient,
  createTaskRun,
  createTestRepo,
  type TestRepo,
} from "../test/fixtures/api";
import { createPostHogHandlers } from "../test/mocks/msw-handlers";
import type { StoredEntry, TaskRun } from "../types";
import {
  AgentServer,
  isTurnCompleteNotification,
  SSE_KEEPALIVE_INTERVAL_MS,
} from "./agent-server";
import { type JwtPayload, SANDBOX_CONNECTION_AUDIENCE } from "./jwt";
import type { ExistingPrCheckoutResult } from "./pr-checkout";

const mockedClaudeSdk = vi.hoisted(() => {
  const createSuccessResult = () => ({
    type: "result",
    subtype: "success",
    duration_ms: 100,
    duration_api_ms: 50,
    is_error: false,
    num_turns: 1,
    result: "Done",
    stop_reason: null,
    total_cost_usd: 0.01,
    usage: {
      input_tokens: 100,
      output_tokens: 50,
      output_tokens_details: { thinking_tokens: 0 },
      cache_read_input_tokens: 0,
      cache_creation_input_tokens: 0,
      cache_creation: {
        ephemeral_1h_input_tokens: 0,
        ephemeral_5m_input_tokens: 0,
      },
      server_tool_use: { web_search_requests: 0, web_fetch_requests: 0 },
      service_tier: "standard",
      inference_geo: "us",
      iterations: [],
      speed: "standard",
    },
    modelUsage: {},
    permission_denials: [],
    uuid: crypto.randomUUID() as `${string}-${string}-${string}-${string}-${string}`,
    session_id: "test-session",
  });

  const query = vi.fn(
    (params: { prompt?: { push?: (message: unknown) => void } }) => {
      const queuedMessages: unknown[] = [];
      let resolveNext: ((value: IteratorResult<unknown, void>) => void) | null =
        null;
      let isDone = false;

      const flushQueue = () => {
        if (!resolveNext) {
          return;
        }

        if (queuedMessages.length > 0) {
          const resolve = resolveNext;
          resolveNext = null;
          resolve({
            value: queuedMessages.shift(),
            done: false,
          });
          return;
        }

        if (isDone) {
          const resolve = resolveNext;
          resolveNext = null;
          resolve({ value: undefined, done: true });
        }
      };

      const enqueue = (message: unknown) => {
        if (isDone) {
          return;
        }
        queuedMessages.push(message);
        flushQueue();
      };

      const prompt = params.prompt;
      if (prompt && typeof prompt.push === "function") {
        const originalPush = prompt.push.bind(prompt);
        prompt.push = (message: unknown) => {
          originalPush(message);

          if (
            message &&
            typeof message === "object" &&
            "uuid" in message &&
            typeof message.uuid === "string"
          ) {
            enqueue({
              type: "user",
              uuid: message.uuid,
              parent_tool_use_id: null,
              message: {
                content: [],
              },
            });
            enqueue(createSuccessResult());
          }
        };
      }

      return {
        next: vi.fn(() => {
          if (queuedMessages.length > 0) {
            return Promise.resolve({
              value: queuedMessages.shift(),
              done: false as const,
            });
          }

          if (isDone) {
            return Promise.resolve({
              value: undefined,
              done: true as const,
            });
          }

          return new Promise<IteratorResult<unknown, void>>((resolve) => {
            resolveNext = resolve;
          });
        }),
        return: vi.fn(() => {
          isDone = true;
          flushQueue();
          return Promise.resolve({ value: undefined, done: true as const });
        }),
        throw: vi.fn((error: Error) => {
          isDone = true;
          flushQueue();
          return Promise.reject(error);
        }),
        [Symbol.asyncIterator]() {
          return this;
        },
        interrupt: vi.fn(async () => {
          isDone = true;
          flushQueue();
        }),
        setPermissionMode: vi.fn().mockResolvedValue(undefined),
        setModel: vi.fn().mockResolvedValue(undefined),
        setMaxThinkingTokens: vi.fn().mockResolvedValue(undefined),
        supportedCommands: vi.fn().mockResolvedValue([]),
        supportedModels: vi.fn().mockResolvedValue([]),
        mcpServerStatus: vi.fn().mockResolvedValue([]),
        accountInfo: vi.fn().mockResolvedValue({}),
        rewindFiles: vi.fn().mockResolvedValue({ canRewind: false }),
        setMcpServers: vi
          .fn()
          .mockResolvedValue({ added: [], removed: [], errors: {} }),
        streamInput: vi.fn().mockResolvedValue(undefined),
        close: vi.fn(),
        initializationResult: vi.fn().mockResolvedValue({
          result: "success",
          commands: [],
          models: [],
        }),
        reconnectMcpServer: vi.fn().mockResolvedValue(undefined),
        toggleMcpServer: vi.fn().mockResolvedValue(undefined),
        supportedAgents: vi.fn().mockResolvedValue([]),
        stopTask: vi.fn().mockResolvedValue(undefined),
        applyFlagSettings: vi.fn().mockResolvedValue(undefined),
        getContextUsage: vi.fn().mockResolvedValue({}),
        reloadPlugins: vi.fn().mockResolvedValue(undefined),
        seedReadState: vi.fn().mockResolvedValue(undefined),
        readFile: vi.fn().mockResolvedValue(""),
        backgroundTasks: vi.fn().mockResolvedValue([]),
        [Symbol.asyncDispose]: vi.fn().mockResolvedValue(undefined),
      };
    },
  );

  return { query };
});

vi.mock("@anthropic-ai/claude-agent-sdk", async (importOriginal) => ({
  ...(await importOriginal()),
  query: mockedClaudeSdk.query,
}));

interface TestableServer {
  getInitialPromptOverride(run: TaskRun): string | null;
  getClearedPendingUserState(run: TaskRun | null): string[] | null;
  clearPendingInitialPromptState(
    payload: JwtPayload,
    run: TaskRun | null,
  ): Promise<void>;
  detectedPrUrl: string | null;
  buildCloudSystemPrompt(
    prUrl?: string | null,
    slackThreadUrl?: string | null,
    inboxReportUrl?: string | null,
  ): string;
  buildDetectedPrContext(prUrl: string): string;
  buildExistingPrCheckoutPromise(
    prUrl: string | null,
  ): Promise<ExistingPrCheckoutResult> | null;
  logExistingPrCheckoutResult(
    prUrl: string | null,
    result: ExistingPrCheckoutResult,
  ): void;
  buildSessionSystemPrompt(
    prUrl?: string | null,
    slackThreadUrl?: string | null,
    inboxReportUrl?: string | null,
  ): string | { append: string };
  buildCodexInstructions(systemPrompt: string | { append: string }): string;
  getRuntimeAdapter(): Adapter;
  buildClaudeCodeSessionMeta(
    runtimeAdapter: Adapter,
  ): { claudeCode: { options: Record<string, unknown> } } | undefined;
  resumeState: ResumeState | null;
  getNativeGoalForFreshSession(
    runtimeAdapter: Adapter,
  ): ResumeState["nativeGoal"];
}

interface NativeResumeTestServer {
  resumeState: ResumeState | null;
  prepareNativeResume(
    payload: JwtPayload,
    posthogAPI: PostHogAPIClient,
    preTaskRun: TaskRun | null,
    runtimeAdapter: Adapter,
    cwd: string,
    permissionMode: PermissionMode,
  ): Promise<{ sessionId: string; warm: boolean } | null>;
}

let nextTestPort = 20000;

function getNextTestPort(): number {
  const port = nextTestPort;
  nextTestPort += 1;
  return port;
}

function exactArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

// The Claude Agent SDK has an internal readMessages() loop that rejects with
// "Query closed before response received" during cleanup. The SDK starts this
// promise in the constructor without a .catch() handler, so the rejection is
// unhandled. We suppress it here to prevent vitest from failing the suite.
type Listener = (...args: unknown[]) => void;
const originalListeners: Listener[] = [];

beforeAll(() => {
  originalListeners.push(
    ...process.rawListeners("unhandledRejection").map((l) => l as Listener),
  );
  process.removeAllListeners("unhandledRejection");
  process.on("unhandledRejection", (reason: unknown) => {
    if (
      reason instanceof Error &&
      reason.message === "Query closed before response received"
    ) {
      return;
    }
    for (const listener of originalListeners) {
      listener(reason);
    }
  });
});

afterAll(() => {
  process.removeAllListeners("unhandledRejection");
  for (const listener of originalListeners) {
    process.on("unhandledRejection", listener);
  }
});

function createTestJwt(
  payload: JwtPayload,
  privateKey: string,
  expiresInSeconds = 3600,
): string {
  return jwt.sign(
    { ...payload, aud: SANDBOX_CONNECTION_AUDIENCE },
    privateKey,
    {
      algorithm: "RS256",
      expiresIn: expiresInSeconds,
    },
  );
}

function sessionUpdateEntry(
  sessionUpdate: string,
  extra: Record<string, unknown> = {},
): StoredEntry {
  return {
    type: "notification",
    timestamp: new Date().toISOString(),
    notification: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update: { sessionUpdate, ...extra } },
    },
  };
}

// Test RSA key pair (2048-bit, for testing only)
const TEST_PRIVATE_KEY = `-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDqh94SYMFsvG4C
Co9BSGjtPr2/OxzuNGr41O4+AMkDQRd9pKO49DhTA4VzwnOvrH8y4eI9N8OQne7B
wpdoouSn4DoDAS/b3SUfij/RoFUSyZiTQoWz0H6o2Vuufiz0Hf+BzlZEVnhSQ1ru
vqSf+4l8cWgeMXaFXgdD5kQ8GjvR5uqKxvO2Env1hMJRKeOOEGgCep/0c6SkMUTX
SeC+VjypVg9+8yPxtIpOQ7XKv+7e/PA0ilqehRQh4fo9BAWjUW1+HnbtsjJAjjfv
ngzIjpajuQVyMi7G79v8OvijhLMJjJBh3TdbVIfi+RkVj/H94UUfKWRfJA0eLykA
VvTiFf0nAgMBAAECggEABkLBQWFW2IXBNAm/IEGEF408uH2l/I/mqSTaBUq1EwKq
U17RRg8y77hg2CHBP9fNf3i7NuIltNcaeA6vRwpOK1MXiVv/QJHLO2fP41Mx4jIC
gi/c7NtsfiprQaG5pnykhP0SnXlndd65bzUkpOasmWdXnbK5VL8ZV40uliInJafE
1Eo9qSYCJxHmivU/4AbiBgygOAo1QIiuuUHcx0YGknLrBaMQETuvWJGE3lxVQ30/
EuRyA3r6BwN2T0z47PZBzvCpg/C1KeoYuKSMwMyEXfl+a8NclqdROkVaenmZpvVH
0lAvFDuPrBSDmU4XJbKCEfwfHjRkiWAFaTrKntGQtQKBgQD/ILoK4U9DkJoKTYvY
9lX7dg6wNO8jGLHNufU8tHhU+QnBMH3hBXrAtIKQ1sGs+D5rq/O7o0Balmct9vwb
CQZ1EpPfa83Thsv6Skd7lWK0JF7g2vVk8kT4nY/eqkgZUWgkfdMp+OMg2drYiIE8
u+sRPTCdq4Tv5miRg0OToX2H/QKBgQDrVR2GXm6ZUyFbCy8A0kttXP1YyXqDVq7p
L4kqyUq43hmbjzIRM4YDN3EvgZvVf6eub6L/3HfKvWD/OvEhHovTvHb9jkwZ3FO+
YQllB/ccAWJs/Dw5jLAsX9O+eIe4lfwROib3vYLnDTAmrXD5VL35R5F0MsdRoxk5
lTCq1sYI8wKBgGA9ZjDIgXAJUjJkwkZb1l9/T1clALiKjjf+2AXIRkQ3lXhs5G9H
8+BRt5cPjAvFsTZIrS6xDIufhNiP/NXt96OeGG4FaqVKihOmhYSW+57cwXWs4zjr
Mx1dwnHKZlw2m0R4unlwy60OwUFBbQ8ODER6gqZXl1Qv5G5Px+Qe3Q25AoGAUl+s
wgfz9r9egZvcjBEQTeuq0pVTyP1ipET7YnqrKSK1G/p3sAW09xNFDzfy8DyK2UhC
agUl+VVoym47UTh8AVWK4R4aDUNOHOmifDbZjHf/l96CxjI0yJOSbq2J9FarsOwG
D9nKJE49eIxlayD6jnM6us27bxwEDF/odSRQlXkCgYEAxn9l/5kewWkeEA0Afe1c
Uf+mepHBLw1Pbg5GJYIZPC6e5+wRNvtFjM5J6h5LVhyb7AjKeLBTeohoBKEfUyUO
rl/ql9qDIh5lJFn3uNh7+r7tmG21Zl2pyh+O8GljjZ25mYhdiwl0uqzVZaINe2Wa
vbMnD1ZQKgL8LHgb02cbTsc=
-----END PRIVATE KEY-----`;

const TEST_PUBLIC_KEY = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6ofeEmDBbLxuAgqPQUho
7T69vzsc7jRq+NTuPgDJA0EXfaSjuPQ4UwOFc8Jzr6x/MuHiPTfDkJ3uwcKXaKLk
p+A6AwEv290lH4o/0aBVEsmYk0KFs9B+qNlbrn4s9B3/gc5WRFZ4UkNa7r6kn/uJ
fHFoHjF2hV4HQ+ZEPBo70ebqisbzthJ79YTCUSnjjhBoAnqf9HOkpDFE10ngvlY8
qVYPfvMj8bSKTkO1yr/u3vzwNIpanoUUIeH6PQQFo1Ftfh527bIyQI43754MyI6W
o7kFcjIuxu/b/Dr4o4SzCYyQYd03W1SH4vkZFY/x/eFFHylkXyQNHi8pAFb04hX9
JwIDAQAB
-----END PUBLIC KEY-----`;

describe("AgentServer HTTP Mode", () => {
  let repo: TestRepo;
  let server: AgentServer | undefined;
  let mswServer: SetupServerApi;
  let appendLogCalls: unknown[][];
  let port: number;

  beforeEach(async () => {
    repo = await createTestRepo("agent-server-http");
    appendLogCalls = [];
    // Use a unique high port per test to avoid reuse and browser-blocked ports.
    port = getNextTestPort();
    mswServer = setupServer(
      ...createPostHogHandlers({
        baseUrl: "http://localhost:8000",
        onAppendLog: (entries) => appendLogCalls.push(entries),
      }),
    );
    mswServer.listen({ onUnhandledRequest: "bypass" });
  });

  afterEach(async () => {
    if (server) {
      await server.stop();
      server = undefined;
    }
    mswServer.close();
    await repo.cleanup();
  });

  const createServer = (
    overrides: Partial<ConstructorParameters<typeof AgentServer>[0]> = {},
  ) => {
    server = new AgentServer({
      port,
      jwtPublicKey: TEST_PUBLIC_KEY,
      repositoryPath: repo.path,
      apiUrl: "http://localhost:8000",
      apiKey: "test-api-key",
      projectId: 1,
      mode: "interactive",
      taskId: "test-task-id",
      runId: "test-run-id",
      resolveRtkSavings: async () => null,
      ...overrides,
    });
    return server;
  };

  const createToken = (overrides = {}) => {
    return createTestJwt(
      {
        run_id: "test-run-id",
        task_id: "test-task-id",
        team_id: 1,
        user_id: 1,
        distinct_id: "test-distinct-id",
        mode: "interactive",
        ...overrides,
      },
      TEST_PRIVATE_KEY,
    );
  };

  it("replays ACP notifications emitted before cloud session assignment", () => {
    const testServer = createServer() as unknown as {
      session: { sseController: null } | null;
      pendingEvents: Record<string, unknown>[];
      preSessionEvents: Record<string, unknown>[];
      handleAcpTransportMessage(message: unknown): void;
      flushPreSessionEvents(): void;
    };
    const message = {
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "available_commands_update",
          availableCommands: [{ name: "goal" }],
        },
      },
    };

    testServer.handleAcpTransportMessage(message);
    expect(testServer.preSessionEvents).toHaveLength(1);

    testServer.session = { sseController: null };
    testServer.flushPreSessionEvents();

    expect(testServer.preSessionEvents).toHaveLength(0);
    expect(testServer.pendingEvents).toContainEqual(
      expect.objectContaining({ notification: message }),
    );
    testServer.session = null;
  });

  describe("GET /health", () => {
    it("returns ok status with active session", async () => {
      await createServer().start();

      const response = await fetch(`http://localhost:${port}/health`);
      const body = await response.json();

      expect(response.status).toBe(200);
      expect(body).toEqual({
        status: "ok",
        hasSession: true,
        bootMs: expect.any(Number),
        sessionInitMs: expect.any(Number),
      });
    }, 30000);

    it("links native agent state before initializing the session", async () => {
      const originalClaudeConfigDir = process.env.CLAUDE_CONFIG_DIR;
      const originalCodexHome = process.env.CODEX_HOME;
      const claudeConfigDir = join(repo.path, ".claude-test");
      const codexHome = join(repo.path, ".codex-test");
      const agentStateDir = join(repo.path, ".posthog", "agent-state");
      process.env.CLAUDE_CONFIG_DIR = claudeConfigDir;
      process.env.CODEX_HOME = codexHome;

      try {
        await createServer({ agentStateDir }).start();

        const claudeProjects = join(claudeConfigDir, "projects");
        const codexSessions = join(codexHome, "sessions");
        expect((await lstat(claudeProjects)).isSymbolicLink()).toBe(true);
        expect((await lstat(codexSessions)).isSymbolicLink()).toBe(true);
        expect(await readlink(claudeProjects)).toBe(
          join(agentStateDir, "claude", "projects"),
        );
        expect(await readlink(codexSessions)).toBe(
          join(agentStateDir, "codex", "sessions"),
        );
      } finally {
        if (originalClaudeConfigDir === undefined) {
          delete process.env.CLAUDE_CONFIG_DIR;
        } else {
          process.env.CLAUDE_CONFIG_DIR = originalClaudeConfigDir;
        }
        if (originalCodexHome === undefined) {
          delete process.env.CODEX_HOME;
        } else {
          process.env.CODEX_HOME = originalCodexHome;
        }
      }
    }, 30000);
  });

  describe("turn completion", () => {
    function stubSessionCleanup(testServer: unknown): {
      session: unknown;
      cleanupSession: (options?: {
        completeEventStream?: boolean;
      }) => Promise<void>;
      eventStreamSender: {
        enqueue: ReturnType<typeof vi.fn>;
        stop: ReturnType<typeof vi.fn>;
      };
    } {
      const cleanupServer = testServer as {
        session: unknown;
        eventStreamSender: {
          enqueue: ReturnType<typeof vi.fn>;
          stop: ReturnType<typeof vi.fn>;
        };
        captureCheckpointState: ReturnType<typeof vi.fn>;
        cleanupSession: (options?: {
          completeEventStream?: boolean;
        }) => Promise<void>;
      };
      cleanupServer.captureCheckpointState = vi.fn(async () => {});
      cleanupServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      cleanupServer.session = {
        payload: { run_id: "run-1" },
        pendingHandoffGitState: undefined,
        logWriter: { flush: vi.fn(async () => {}) },
        acpConnection: { cleanup: vi.fn(async () => {}) },
        sseController: { close: vi.fn() },
      };
      return cleanupServer;
    }

    it("keeps event ingest open for non-terminal session cleanup", async () => {
      const testServer = stubSessionCleanup(createServer());

      await testServer.cleanupSession();

      expect(testServer.eventStreamSender.enqueue).not.toHaveBeenCalled();
      expect(testServer.eventStreamSender.stop).not.toHaveBeenCalled();
    });

    it("stops event ingest for terminal session cleanup without fake task completion", async () => {
      const testServer = stubSessionCleanup(createServer());

      await testServer.cleanupSession({ completeEventStream: true });

      expect(testServer.eventStreamSender.enqueue).not.toHaveBeenCalled();
      expect(testServer.eventStreamSender.stop).toHaveBeenCalledOnce();
    });

    it("emits rtk savings once before terminal event ingest stops", async () => {
      const testServer = stubSessionCleanup(
        createServer({
          resolveRtkSavings: async () => ({
            totalCommands: 4,
            inputTokens: 1000,
            outputTokens: 350,
            tokensSaved: 650,
          }),
        }),
      );
      const session = testServer.session;

      await testServer.cleanupSession({ completeEventStream: true });
      testServer.session = session;
      await testServer.cleanupSession({ completeEventStream: true });

      expect(testServer.eventStreamSender.enqueue).toHaveBeenCalledOnce();
      expect(testServer.eventStreamSender.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          notification: expect.objectContaining({
            method: "_posthog/rtk_savings",
            params: expect.objectContaining({
              task_id: "test-task-id",
              run_id: "test-run-id",
              team_id: 1,
              counter_id: "test-task-id",
              cumulative_commands: 4,
              cumulative_input_tokens: 1000,
              cumulative_output_tokens: 350,
              cumulative_tokens_saved: 650,
            }),
          }),
        }),
      );
      expect(
        testServer.eventStreamSender.enqueue.mock.invocationCallOrder[0],
      ).toBeLessThan(
        testServer.eventStreamSender.stop.mock.invocationCallOrder[0],
      );
    });

    it("writes terminal failure status before completing event ingest", async () => {
      const order: string[] = [];
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
        resolveRtkSavings: async () => null,
      }) as unknown as {
        eventStreamSender: {
          enqueue: (event: Record<string, unknown>) => void;
          stop: () => Promise<void>;
        };
        posthogAPI: {
          updateTaskRun: (
            taskId: string,
            runId: string,
            payload: Record<string, unknown>,
          ) => Promise<unknown>;
        };
        signalTaskComplete(
          payload: JwtPayload,
          stopReason: string,
          errorMessage?: string,
        ): Promise<void>;
      };
      testServer.eventStreamSender = {
        enqueue: vi.fn(() => {
          order.push("enqueue");
        }),
        stop: vi.fn(async () => {
          order.push("stop");
        }),
      };
      testServer.posthogAPI = {
        updateTaskRun: vi.fn(async () => {
          order.push("update");
          return {};
        }),
      };

      await testServer.signalTaskComplete(
        {
          run_id: "run-1",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode: "interactive",
        },
        "error",
        "boom",
      );

      expect(order).toEqual(["enqueue", "update", "stop"]);
      expect(testServer.eventStreamSender.enqueue).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "notification",
          notification: expect.objectContaining({
            method: "_posthog/error",
            params: expect.objectContaining({ error: "boom" }),
          }),
        }),
      );
      expect(testServer.posthogAPI.updateTaskRun).toHaveBeenCalledWith(
        "task-1",
        "run-1",
        {
          status: "failed",
          error_message: "boom",
        },
      );
    });

    it("still stops event ingest when terminal failure status update fails", async () => {
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
        resolveRtkSavings: async () => null,
      }) as unknown as {
        eventStreamSender: {
          enqueue: (event: Record<string, unknown>) => void;
          stop: () => Promise<void>;
        };
        posthogAPI: {
          updateTaskRun: (
            taskId: string,
            runId: string,
            payload: Record<string, unknown>,
          ) => Promise<unknown>;
        };
        signalTaskComplete(
          payload: JwtPayload,
          stopReason: string,
          errorMessage?: string,
        ): Promise<void>;
      };
      testServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      testServer.posthogAPI = {
        updateTaskRun: vi.fn(async () => {
          throw new Error("update failed");
        }),
      };

      await testServer.signalTaskComplete(
        {
          run_id: "run-1",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode: "interactive",
        },
        "error",
        "boom",
      );

      expect(testServer.eventStreamSender.enqueue).toHaveBeenCalledOnce();
      expect(testServer.posthogAPI.updateTaskRun).toHaveBeenCalledOnce();
      expect(testServer.eventStreamSender.stop).toHaveBeenCalledOnce();
    });

    it("leaves event ingest open for non-error stop reasons", async () => {
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
      }) as unknown as {
        eventStreamSender: {
          enqueue: (event: Record<string, unknown>) => void;
          stop: () => Promise<void>;
        };
        posthogAPI: {
          updateTaskRun: (
            taskId: string,
            runId: string,
            payload: Record<string, unknown>,
          ) => Promise<unknown>;
        };
        signalTaskComplete(
          payload: JwtPayload,
          stopReason: string,
        ): Promise<void>;
      };
      testServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      testServer.posthogAPI = {
        updateTaskRun: vi.fn(async () => ({})),
      };

      await testServer.signalTaskComplete(
        {
          run_id: "run-1",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode: "interactive",
        },
        "end_turn",
      );

      expect(testServer.eventStreamSender.enqueue).not.toHaveBeenCalled();
      expect(testServer.eventStreamSender.stop).not.toHaveBeenCalled();
      expect(testServer.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
    });

    function createUsageTestServer() {
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
      }) as unknown as {
        session: { payload: JwtPayload } | null;
        posthogAPI: { updateTaskRun: ReturnType<typeof vi.fn> };
        recordTurnUsage(usage: unknown): void;
      };
      testServer.posthogAPI = { updateTaskRun: vi.fn(async () => ({})) };
      testServer.session = {
        payload: {
          run_id: "run-1",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode: "interactive",
        },
      };
      return testServer;
    }

    it("reports cumulative run token usage into TaskRun.state after each settled turn", () => {
      const testServer = createUsageTestServer();
      const turnUsage = {
        inputTokens: 100,
        outputTokens: 50,
        cachedReadTokens: 10,
        cachedWriteTokens: 5,
        totalTokens: 165,
      };

      testServer.recordTurnUsage(turnUsage);
      testServer.recordTurnUsage(turnUsage);

      expect(testServer.posthogAPI.updateTaskRun).toHaveBeenCalledTimes(2);
      expect(testServer.posthogAPI.updateTaskRun).toHaveBeenNthCalledWith(
        1,
        "task-1",
        "run-1",
        {
          state: {
            token_usage: {
              input_tokens: 100,
              output_tokens: 50,
              cache_read_tokens: 10,
              cache_write_tokens: 5,
              thought_tokens: 0,
              total_tokens: 165,
              turns: 1,
            },
          },
        },
      );
      // The second report carries run-cumulative totals, not per-turn figures.
      expect(testServer.posthogAPI.updateTaskRun).toHaveBeenLastCalledWith(
        "task-1",
        "run-1",
        {
          state: {
            token_usage: {
              input_tokens: 200,
              output_tokens: 100,
              cache_read_tokens: 20,
              cache_write_tokens: 10,
              thought_tokens: 0,
              total_tokens: 330,
              turns: 2,
            },
          },
        },
      );
    });

    it("does not report anything when a turn settles without usage", () => {
      const testServer = createUsageTestServer();

      testServer.recordTurnUsage(undefined);

      expect(testServer.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
    });

    it("resets run usage on session cleanup so a later run starts from zero", async () => {
      const testServer = createUsageTestServer();
      const turnUsage = {
        inputTokens: 100,
        outputTokens: 50,
        totalTokens: 150,
      };
      testServer.recordTurnUsage(turnUsage);

      const cleanupServer = stubSessionCleanup(testServer);
      await cleanupServer.cleanupSession();

      testServer.session = {
        payload: {
          run_id: "run-2",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode: "interactive",
        },
      };
      testServer.recordTurnUsage(turnUsage);

      expect(testServer.posthogAPI.updateTaskRun).toHaveBeenLastCalledWith(
        "task-1",
        "run-2",
        {
          state: {
            token_usage: {
              input_tokens: 100,
              output_tokens: 50,
              cache_read_tokens: 0,
              cache_write_tokens: 0,
              thought_tokens: 0,
              total_tokens: 150,
              turns: 1,
            },
          },
        },
      );
    });

    // Sandbox teardown kills the exec'd agent-server without SIGTERM, so the
    // trace's root span only exports if telemetry is shut down at the run's
    // in-process terminal points.
    it("shuts down telemetry after mirroring the terminal failure record", async () => {
      const order: string[] = [];
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
      }) as unknown as {
        session: {
          payload: { run_id: string };
          logWriter: { flush: ReturnType<typeof vi.fn> };
          telemetry: {
            append: ReturnType<typeof vi.fn>;
            shutdown: ReturnType<typeof vi.fn>;
          };
        };
        eventStreamSender: {
          enqueue: (event: Record<string, unknown>) => void;
          stop: () => Promise<void>;
        };
        posthogAPI: {
          updateTaskRun: (
            taskId: string,
            runId: string,
            payload: Record<string, unknown>,
          ) => Promise<unknown>;
        };
        signalTaskComplete(
          payload: JwtPayload,
          stopReason: string,
          errorMessage?: string,
        ): Promise<void>;
      };
      testServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      testServer.posthogAPI = {
        updateTaskRun: vi.fn(async () => ({})),
      };
      testServer.session = {
        payload: { run_id: "run-1" },
        logWriter: { flush: vi.fn(async () => {}) },
        telemetry: {
          append: vi.fn(() => {
            order.push("append");
          }),
          shutdown: vi.fn(async () => {
            order.push("shutdown");
          }),
        },
      };

      await testServer.signalTaskComplete(
        {
          run_id: "run-1",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode: "background",
        },
        "error",
        "boom",
      );

      // The error mirror must land before shutdown so the root span exports
      // with ERROR status.
      expect(order).toEqual(["append", "shutdown"]);
    });

    it.each([
      { mode: "background" as const, shutdownCalls: 1 },
      { mode: "interactive" as const, shutdownCalls: 0 },
    ])(
      "finalizeRunTelemetry shuts down telemetry only for $mode runs",
      async ({ mode, shutdownCalls }) => {
        const testServer = new AgentServer({
          port,
          jwtPublicKey: TEST_PUBLIC_KEY,
          repositoryPath: repo.path,
          apiUrl: "http://localhost:8000",
          apiKey: "test-api-key",
          projectId: 1,
          mode: "interactive",
          taskId: "test-task-id",
          runId: "test-run-id",
        }) as unknown as {
          session: { telemetry: { shutdown: ReturnType<typeof vi.fn> } };
          finalizeRunTelemetry(payload: JwtPayload): Promise<void>;
        };
        testServer.session = {
          telemetry: { shutdown: vi.fn(async () => {}) },
        };

        await testServer.finalizeRunTelemetry({
          run_id: "run-1",
          task_id: "task-1",
          team_id: 1,
          user_id: 1,
          distinct_id: "distinct-id",
          mode,
        });

        expect(testServer.session.telemetry.shutdown).toHaveBeenCalledTimes(
          shutdownCalls,
        );
      },
    );

    function createFailureTestServer() {
      const appendRawLine = vi.fn();
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
      }) as unknown as {
        eventStreamSender: {
          enqueue: ReturnType<typeof vi.fn>;
          stop: ReturnType<typeof vi.fn>;
        };
        posthogAPI: { updateTaskRun: ReturnType<typeof vi.fn> };
        session: unknown;
        handleTurnFailure(
          payload: JwtPayload,
          phase: "initial" | "resume" | "followup",
          error: unknown,
        ): Promise<void>;
      };
      testServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      testServer.posthogAPI = { updateTaskRun: vi.fn(async () => ({})) };
      testServer.session = {
        acpSessionId: "acp-1",
        payload: { run_id: "run-1" },
        logWriter: { appendRawLine, flush: vi.fn(async () => {}) },
      };
      return testServer;
    }

    const interactivePayload: JwtPayload = {
      run_id: "run-1",
      task_id: "task-1",
      team_id: 1,
      user_id: 1,
      distinct_id: "distinct-id",
      mode: "interactive",
    };

    it.each([
      ["genuine agent error (terminal)", "boom", "agent_error", true],
      [
        "transient upstream timeout (recoverable)",
        "API Error: The operation timed out.",
        "upstream_timeout",
        false,
      ],
    ] as const)(
      "tags and handles a follow-up %s",
      async (_name, errorMessage, expectedErrorType, expectsFailed) => {
        const testServer = createFailureTestServer();

        await testServer.handleTurnFailure(
          interactivePayload,
          "followup",
          new Error(errorMessage),
        );

        expect(testServer.eventStreamSender.enqueue).toHaveBeenCalledWith(
          expect.objectContaining({
            notification: expect.objectContaining({
              method: "session/update",
              params: expect.objectContaining({
                update: expect.objectContaining({
                  sessionUpdate: "error",
                  errorType: expectedErrorType,
                }),
              }),
            }),
          }),
        );

        if (expectsFailed) {
          expect(testServer.posthogAPI.updateTaskRun).toHaveBeenCalledWith(
            "task-1",
            "run-1",
            expect.objectContaining({ status: "failed" }),
          );
        } else {
          expect(testServer.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
        }
      },
    );

    function createRetryTestServer(prompt: ReturnType<typeof vi.fn>) {
      const testServer = createFailureTestServer();
      testServer.session = {
        acpSessionId: "acp-1",
        payload: { run_id: "run-1" },
        logWriter: { appendRawLine: vi.fn(), flush: vi.fn(async () => {}) },
        clientConnection: { prompt },
      };
      return testServer as unknown as {
        promptWithUpstreamRetry(request: {
          sessionId: string;
          prompt: ContentBlock[];
        }): Promise<{ stopReason: string }>;
      };
    }

    it("continues an unattended turn after a transient upstream stream death", async () => {
      vi.useFakeTimers();
      try {
        const prompt = vi
          .fn()
          .mockRejectedValueOnce(new Error("API Error: terminated"))
          .mockResolvedValueOnce({ stopReason: "end_turn" });
        const testServer = createRetryTestServer(prompt);

        const resultPromise = testServer.promptWithUpstreamRetry({
          sessionId: "acp-1",
          prompt: [{ type: "text", text: "do the task" }],
        });
        await vi.advanceTimersByTimeAsync(5_000);

        await expect(resultPromise).resolves.toEqual({
          stopReason: "end_turn",
        });
        expect(prompt).toHaveBeenCalledTimes(2);
        const retryRequest = prompt.mock.calls[1][0] as {
          sessionId: string;
          prompt: Array<{ type: string; text: string }>;
        };
        expect(retryRequest.sessionId).toBe("acp-1");
        expect(retryRequest.prompt[0].text).toContain(
          "interrupted by a transient connection error",
        );
      } finally {
        vi.useRealTimers();
      }
    });

    it("re-sends the original prompt when the failure happened before the stream started", async () => {
      vi.useFakeTimers();
      try {
        const prompt = vi
          .fn()
          .mockRejectedValueOnce(new Error("API Error: Connection error."))
          .mockResolvedValueOnce({ stopReason: "end_turn" });
        const testServer = createRetryTestServer(prompt);

        const resultPromise = testServer.promptWithUpstreamRetry({
          sessionId: "acp-1",
          prompt: [{ type: "text", text: "do the task" }],
        });
        await vi.advanceTimersByTimeAsync(5_000);

        await expect(resultPromise).resolves.toEqual({
          stopReason: "end_turn",
        });
        expect(prompt).toHaveBeenCalledTimes(2);
        const retryRequest = prompt.mock.calls[1][0] as {
          sessionId: string;
          prompt: Array<{ type: string; text: string }>;
        };
        expect(retryRequest.sessionId).toBe("acp-1");
        expect(retryRequest.prompt).toEqual([
          { type: "text", text: "do the task" },
        ]);
      } finally {
        vi.useRealTimers();
      }
    });

    it("does not retry a genuine agent error", async () => {
      const prompt = vi.fn().mockRejectedValue(new Error("boom"));
      const testServer = createRetryTestServer(prompt);

      await expect(
        testServer.promptWithUpstreamRetry({
          sessionId: "acp-1",
          prompt: [{ type: "text", text: "do the task" }],
        }),
      ).rejects.toThrow("boom");
      expect(prompt).toHaveBeenCalledTimes(1);
    });

    it("stops continuing once the bounded retry budget is exhausted", async () => {
      vi.useFakeTimers();
      try {
        const prompt = vi
          .fn()
          .mockRejectedValue(new Error("API Error: terminated"));
        const testServer = createRetryTestServer(prompt);

        const resultPromise = testServer.promptWithUpstreamRetry({
          sessionId: "acp-1",
          prompt: [{ type: "text", text: "do the task" }],
        });
        const assertion = expect(resultPromise).rejects.toThrow(
          "API Error: terminated",
        );
        await vi.advanceTimersByTimeAsync(10_000);

        await assertion;
        expect(prompt).toHaveBeenCalledTimes(3);
      } finally {
        vi.useRealTimers();
      }
    });

    it("persists structured turn completion notifications", () => {
      const appendRawLine = vi.fn();
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
      }) as unknown as {
        session: unknown;
        broadcastTurnComplete(stopReason: string): void;
      };
      testServer.session = {
        acpSessionId: "session-1",
        payload: { run_id: "run-1" },
        logWriter: { appendRawLine },
      };

      testServer.broadcastTurnComplete("end_turn");

      expect(appendRawLine).toHaveBeenCalledTimes(1);
      expect(appendRawLine.mock.calls[0][0]).toBe("run-1");
      expect(JSON.parse(appendRawLine.mock.calls[0][1])).toEqual({
        jsonrpc: "2.0",
        method: "_posthog/turn_complete",
        params: {
          sessionId: "session-1",
          stopReason: "end_turn",
        },
      });
    });

    it("skips one broadcast after the adapter emitted its own turn_complete", () => {
      const appendRawLine = vi.fn();
      const testServer = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
      }) as unknown as {
        session: unknown;
        adapterEmittedTurnComplete: boolean;
        broadcastTurnComplete(stopReason: string): void;
      };
      testServer.session = {
        acpSessionId: "session-1",
        payload: { run_id: "run-1" },
        logWriter: { appendRawLine },
      };
      testServer.adapterEmittedTurnComplete = true;

      testServer.broadcastTurnComplete("end_turn");
      expect(appendRawLine).not.toHaveBeenCalled();

      testServer.broadcastTurnComplete("end_turn");
      expect(appendRawLine).toHaveBeenCalledTimes(1);
    });

    it("recognizes adapter turn_complete notifications on the tapped stream", () => {
      expect(
        isTurnCompleteNotification({
          jsonrpc: "2.0",
          method: "_posthog/turn_complete",
          params: { sessionId: "s", stopReason: "end_turn" },
        }),
      ).toBe(true);
      expect(
        isTurnCompleteNotification({
          jsonrpc: "2.0",
          method: "_posthog/usage_update",
          params: {},
        }),
      ).toBe(false);
      expect(isTurnCompleteNotification(null)).toBe(false);
      expect(isTurnCompleteNotification("turn_complete")).toBe(false);
    });
  });

  describe("broadcastEvent", () => {
    function exposeBroadcastEvent(testServer: AgentServer) {
      return testServer as unknown as {
        eventStreamSender: {
          enqueue: ReturnType<typeof vi.fn>;
          stop: ReturnType<typeof vi.fn>;
        } | null;
        pendingEvents: Record<string, unknown>[];
        session: unknown;
        broadcastEvent(event: Record<string, unknown>): void;
      };
    }

    it("enqueues and buffers events raised before a session is assigned", () => {
      // Regression: an MCP relay request can fire the instant the client
      // subprocess starts, ahead of session assignment. broadcastEvent must
      // not silently drop it.
      const testServer = exposeBroadcastEvent(createServer());
      testServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      testServer.session = null;

      const event = {
        type: "mcp_request",
        requestId: "req-1",
        server: "slack",
      };
      testServer.broadcastEvent(event);

      expect(testServer.eventStreamSender.enqueue).toHaveBeenCalledWith(event);
      expect(testServer.pendingEvents).toEqual([event]);
    });

    it("buffers events with no event stream sender configured and no session", () => {
      const testServer = exposeBroadcastEvent(createServer());
      testServer.session = null;

      const event = {
        type: "mcp_request",
        requestId: "req-1",
        server: "slack",
      };
      expect(() => testServer.broadcastEvent(event)).not.toThrow();

      expect(testServer.pendingEvents).toEqual([event]);
    });
  });

  describe("relayed MCP server tool permissions", () => {
    function exposeCloudClient(testServer: AgentServer) {
      return testServer as unknown as {
        config: { relayMcpServers?: string[]; mode?: string };
        session: { hasDesktopConnected?: boolean } | null;
        eventStreamSender: unknown;
        relayPermissionToClient: (params: unknown) => Promise<unknown>;
        pendingPermissions: Map<string, unknown>;
        resolvePermission: (
          requestId: string,
          optionId: string,
        ) => "resolved" | "not_found" | "invalid_option";
        createCloudClient(payload: {
          run_id: string;
          task_id: string;
          team_id: number;
          user_id: number;
          distinct_id: string;
          mode?: "interactive" | "background";
        }): {
          requestPermission(params: unknown): Promise<{
            outcome: { outcome: string; optionId?: string };
            _meta?: Record<string, unknown>;
          }>;
        };
      };
    }

    function permissionRequestFor(mcpToolName: string) {
      return {
        options: [{ optionId: "allow_once", kind: "allow_once" }],
        toolCall: {
          kind: "other",
          _meta: { claudeCode: { toolName: mcpToolName } },
          rawInput: {},
        },
      };
    }

    // Codex never writes `_meta.claudeCode`; it populates the neutral
    // `_meta.posthog` channel with a structured `mcp` descriptor and sets
    // rawInput to the tool arguments (no toolName). The gate must still fire.
    function codexPermissionRequestFor(server: string, tool: string) {
      return {
        options: [{ optionId: "allow_once", kind: "allow_once" }],
        toolCall: {
          kind: "other",
          _meta: {
            posthog: {
              toolName: `mcp__${server}__${tool}`,
              mcp: { server, tool },
            },
          },
          rawInput: { some: "arg" },
        },
      };
    }

    function posthogExecPermissionOptions() {
      return [
        { optionId: "allow_once", kind: "allow_once" },
        { optionId: "allow_always", kind: "allow_always" },
        { optionId: "reject_once", kind: "reject_once" },
      ];
    }

    function claudePosthogExecPermissionRequest(command: string) {
      return {
        options: posthogExecPermissionOptions(),
        toolCall: {
          kind: "other",
          _meta: { claudeCode: { toolName: "mcp__posthog__exec" } },
          rawInput: { command },
        },
      };
    }

    function codexPosthogExecPermissionRequest(command: string) {
      return {
        options: posthogExecPermissionOptions(),
        toolCall: {
          kind: "other",
          _meta: {
            posthog: {
              toolName: "mcp__posthog_cloud__exec",
              mcp: { server: "posthog_cloud", tool: "exec" },
            },
          },
          rawInput: { command },
        },
      };
    }

    const basePayload = {
      run_id: "run-1",
      task_id: "task-1",
      team_id: 1,
      user_id: 1,
      distinct_id: "user-1",
    };

    it("relays a relayed-server tool call when the desktop is connected", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = { hasDesktopConnected: true };
      const relaySpy = vi
        .spyOn(testServer, "relayPermissionToClient")
        .mockResolvedValue({
          outcome: { outcome: "selected", optionId: "allow_once" },
        });

      const { requestPermission } = testServer.createCloudClient(basePayload);
      const result = await requestPermission(
        permissionRequestFor("mcp__slack__send_message"),
      );

      expect(relaySpy).toHaveBeenCalledOnce();
      expect(result).toEqual({
        outcome: { outcome: "selected", optionId: "allow_once" },
      });
    });

    it("relays when only the durable event stream is reachable (no desktop session)", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = null;
      testServer.eventStreamSender = {
        enqueue: vi.fn(),
        stop: vi.fn(async () => {}),
      };
      const relaySpy = vi
        .spyOn(testServer, "relayPermissionToClient")
        .mockResolvedValue({
          outcome: { outcome: "selected", optionId: "allow_once" },
        });

      const { requestPermission } = testServer.createCloudClient(basePayload);
      await requestPermission(permissionRequestFor("mcp__slack__send_message"));

      expect(relaySpy).toHaveBeenCalledOnce();
    });

    it("denies a relayed-server tool call instead of auto-approving when no client is reachable", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = null;
      testServer.eventStreamSender = null;
      const relaySpy = vi.spyOn(testServer, "relayPermissionToClient");

      const { requestPermission } = testServer.createCloudClient(basePayload);
      const result = await requestPermission(
        permissionRequestFor("mcp__slack__send_message"),
      );

      expect(relaySpy).not.toHaveBeenCalled();
      expect(result.outcome).toEqual({ outcome: "cancelled" });
    });

    it("denies a relayed-server tool call in background mode even when a client is reachable", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = { hasDesktopConnected: true };
      const relaySpy = vi.spyOn(testServer, "relayPermissionToClient");

      const { requestPermission } = testServer.createCloudClient({
        ...basePayload,
        mode: "background",
      });
      const result = await requestPermission(
        permissionRequestFor("mcp__slack__send_message"),
      );

      expect(relaySpy).not.toHaveBeenCalled();
      expect(result.outcome).toEqual({ outcome: "cancelled" });
    });

    it("does not treat a tool on a non-relayed server as always-ask", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = null;
      testServer.eventStreamSender = null;
      const relaySpy = vi.spyOn(testServer, "relayPermissionToClient");

      const { requestPermission } = testServer.createCloudClient(basePayload);
      const result = await requestPermission(
        permissionRequestFor("mcp__posthog__query"),
      );

      expect(relaySpy).not.toHaveBeenCalled();
      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "allow_once",
      });
    });

    it("treats a codex relay tool call (posthog _meta channel) as always-ask", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = { hasDesktopConnected: true };
      const relaySpy = vi
        .spyOn(testServer, "relayPermissionToClient")
        .mockResolvedValue({
          outcome: { outcome: "selected", optionId: "allow_once" },
        });

      const { requestPermission } = testServer.createCloudClient(basePayload);
      await requestPermission(
        codexPermissionRequestFor("slack", "send_message"),
      );

      expect(relaySpy).toHaveBeenCalledOnce();
    });

    it("denies a codex relay tool call when no client is reachable", async () => {
      const testServer = exposeCloudClient(createServer());
      testServer.config.relayMcpServers = ["slack"];
      testServer.session = null;
      testServer.eventStreamSender = null;
      const relaySpy = vi.spyOn(testServer, "relayPermissionToClient");

      const { requestPermission } = testServer.createCloudClient(basePayload);
      const result = await requestPermission(
        codexPermissionRequestFor("slack", "send_message"),
      );

      expect(relaySpy).not.toHaveBeenCalled();
      expect(result.outcome).toEqual({ outcome: "cancelled" });
    });

    it.each([
      {
        adapter: "Claude",
        request: claudePosthogExecPermissionRequest(
          "call notebooks-destroy {}",
        ),
        expectedKinds: ["allow_once", "allow_always", "reject_once"],
      },
      {
        adapter: "Codex",
        request: codexPosthogExecPermissionRequest("call notebooks-destroy {}"),
        expectedKinds: ["allow_once", "reject_once"],
      },
    ])(
      "relays a configured PostHog exec match from $adapter with adapter-specific choices",
      async ({ request, expectedKinds }) => {
        const testServer = exposeCloudClient(createServer());
        testServer.session = null;
        testServer.eventStreamSender = null;
        const relaySpy = vi
          .spyOn(testServer, "relayPermissionToClient")
          .mockResolvedValue({
            outcome: { outcome: "selected", optionId: "allow_once" },
          });

        const { requestPermission } = testServer.createCloudClient(basePayload);
        const result = await requestPermission(request);

        const relayed = relaySpy.mock.calls[0]?.[0] as {
          options: Array<{ kind: string }>;
        };
        expect(relayed.options.map((option) => option.kind)).toEqual(
          expectedKinds,
        );
        expect(result.outcome).toEqual({
          outcome: "selected",
          optionId: "allow_once",
        });
      },
    );

    it("auto-approves a nonmatching PostHog exec sub-tool", async () => {
      const testServer = exposeCloudClient(
        createServer({ posthogExecPermissionRegex: "delete|destroy" }),
      );
      const relaySpy = vi.spyOn(testServer, "relayPermissionToClient");

      const { requestPermission } = testServer.createCloudClient(basePayload);
      const result = await requestPermission(
        claudePosthogExecPermissionRequest("call experiment-get {}"),
      );

      expect(relaySpy).not.toHaveBeenCalled();
      expect(result.outcome).toEqual({
        outcome: "selected",
        optionId: "allow_once",
      });
    });

    it.each([
      {
        modeSource: "JWT payload",
        configMode: "interactive",
        payloadMode: "background",
      },
      {
        modeSource: "server config",
        configMode: "background",
        payloadMode: undefined,
      },
    ] as const)(
      "keeps PostHog exec matches auto-approved in background mode from $modeSource",
      async ({ configMode, payloadMode }) => {
        const testServer = exposeCloudClient(
          createServer({
            mode: configMode,
            posthogExecPermissionRegex: "delete|destroy",
          }),
        );
        const relaySpy = vi.spyOn(testServer, "relayPermissionToClient");

        const { requestPermission } = testServer.createCloudClient({
          ...basePayload,
          ...(payloadMode ? { mode: payloadMode } : {}),
        });
        const result = await requestPermission(
          codexPosthogExecPermissionRequest("call experiment-delete {}"),
        );

        expect(relaySpy).not.toHaveBeenCalled();
        expect(result.outcome).toEqual({
          outcome: "selected",
          optionId: "allow_once",
        });
      },
    );

    it("rejects permission responses for options that were not offered", async () => {
      const testServer = exposeCloudClient(createServer());
      const pending = testServer.relayPermissionToClient({
        options: [
          { optionId: "allow_once", kind: "allow_once" },
          { optionId: "reject_once", kind: "reject_once" },
        ],
      });
      const requestId = [...testServer.pendingPermissions.keys()][0];

      expect(requestId).toBeDefined();
      expect(
        testServer.resolvePermission(requestId as string, "allow_always"),
      ).toBe("invalid_option");
      expect(testServer.pendingPermissions.has(requestId as string)).toBe(true);
      expect(testServer.resolvePermission("nope", "allow_once")).toBe(
        "not_found",
      );
      expect(
        testServer.resolvePermission(requestId as string, "allow_once"),
      ).toBe("resolved");
      await expect(pending).resolves.toEqual({
        outcome: { outcome: "selected", optionId: "allow_once" },
      });
    });

    it("distinguishes unknown requests from unoffered options in permission_response errors", async () => {
      const server = createServer();
      const testServer = exposeCloudClient(server);
      const commandServer = server as unknown as {
        session: unknown;
        executeCommand(
          method: string,
          params: Record<string, unknown>,
        ): Promise<unknown>;
      };
      void testServer.relayPermissionToClient({
        options: [{ optionId: "allow_once", kind: "allow_once" }],
      });
      const requestId = [...testServer.pendingPermissions.keys()][0] as string;
      // Both error paths return before touching the session; the guard at the
      // top of executeCommand only needs it to exist.
      commandServer.session = {};

      await expect(
        commandServer.executeCommand("permission_response", {
          requestId: "missing",
          optionId: "allow_once",
        }),
      ).rejects.toThrow("No pending permission request found for id: missing");
      await expect(
        commandServer.executeCommand("permission_response", {
          requestId,
          optionId: "allow_always",
        }),
      ).rejects.toThrow(
        `Option "allow_always" was not offered for permission request ${requestId}`,
      );
      expect(testServer.pendingPermissions.has(requestId)).toBe(true);
    });
  });

  describe("refresh_session relay re-append", () => {
    function exposeRefresh(testServer: AgentServer) {
      return testServer as unknown as {
        session: {
          clientConnection: { extMethod: ReturnType<typeof vi.fn> };
        } | null;
        mcpRelayServer: { mcpServers: unknown[] } | null;
        executeCommand(
          method: string,
          params: Record<string, unknown>,
        ): Promise<unknown>;
      };
    }

    it("re-appends the loopback relay entries so a refresh doesn't drop them", async () => {
      const testServer = exposeRefresh(createServer());
      const extMethod = vi.fn(async () => ({ refreshed: true }));
      testServer.session = { clientConnection: { extMethod } };
      const relayEntry = {
        type: "http",
        name: "slack",
        url: "http://127.0.0.1:5555/relay/slack",
        headers: [{ name: "Authorization", value: "Bearer secret" }],
      };
      testServer.mcpRelayServer = { mcpServers: [relayEntry] };

      // Django's refresh list carries posthog + imported, never the relay entries.
      await testServer.executeCommand("refresh_session", {
        mcpServers: [
          { type: "http", name: "posthog", url: "https://mcp", headers: [] },
        ],
      });

      expect(extMethod).toHaveBeenCalledOnce();
      const forwarded = (extMethod.mock.calls[0] as unknown[])[1] as {
        mcpServers: Array<{ name: string }>;
      };
      expect(forwarded.mcpServers.map((s) => s.name)).toEqual([
        "posthog",
        "slack",
      ]);

      // Detach the fake session so afterEach's stop() short-circuits before
      // touching the partial session/relay stubs.
      testServer.session = null;
    });

    it("does not duplicate a relay entry already present in the refresh list", async () => {
      const testServer = exposeRefresh(createServer());
      const extMethod = vi.fn(async () => ({ refreshed: true }));
      testServer.session = { clientConnection: { extMethod } };
      testServer.mcpRelayServer = {
        mcpServers: [
          {
            type: "http",
            name: "slack",
            url: "http://127.0.0.1:5555/relay/slack",
            headers: [],
          },
        ],
      };

      await testServer.executeCommand("refresh_session", {
        mcpServers: [
          {
            type: "http",
            name: "slack",
            url: "http://127.0.0.1:5555/relay/slack",
            headers: [],
          },
        ],
      });

      const forwarded = (extMethod.mock.calls[0] as unknown[])[1] as {
        mcpServers: Array<{ name: string }>;
      };
      expect(forwarded.mcpServers.map((s) => s.name)).toEqual(["slack"]);

      testServer.session = null;
    });
  });

  describe("GET /events", () => {
    it("returns 401 without authorization header", async () => {
      await createServer().start();

      const response = await fetch(`http://localhost:${port}/events`);
      const body = await response.json();

      expect(response.status).toBe(401);
      expect(body.error).toBe("Missing authorization header");
    }, 20000);

    it("returns 401 with invalid token", async () => {
      await createServer().start();

      const response = await fetch(`http://localhost:${port}/events`, {
        headers: { Authorization: "Bearer invalid-token" },
      });
      const body = await response.json();

      expect(response.status).toBe(401);
      expect(body.code).toBe("invalid_signature");
    }, 20000);

    it("accepts valid JWT and returns SSE stream", async () => {
      await createServer().start();
      const token = createToken();

      const response = await fetch(`http://localhost:${port}/events`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toBe("text/event-stream");
    }, 20000);

    it("emits transport keepalive comments while idle", async () => {
      const keepaliveCallback: { current: (() => void) | null } = {
        current: null,
      };
      // Pass through to real setInterval for non-keepalive timers; otherwise
      // unrelated internals (undici, http server, MSW) lose their periodic
      // callbacks and can hang the test.
      const realSetInterval = globalThis.setInterval;
      const setIntervalSpy = vi
        .spyOn(globalThis, "setInterval")
        .mockImplementation(((
          callback: (_: undefined) => void,
          timeout?: number,
          ...args: unknown[]
        ) => {
          if (timeout === SSE_KEEPALIVE_INTERVAL_MS) {
            keepaliveCallback.current = () => callback(undefined);
            return setTimeout(() => undefined, 60_000);
          }
          return (realSetInterval as (...rest: unknown[]) => unknown)(
            callback,
            timeout,
            ...args,
          );
        }) as unknown as typeof setInterval);

      let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
      try {
        const testServer = createServer() as unknown as {
          app: {
            fetch: (request: Request) => Promise<Response> | Response;
          };
          session: unknown;
        };
        testServer.session = {
          payload: {
            run_id: "test-run-id",
            task_id: "test-task-id",
            team_id: 1,
            user_id: 1,
            distinct_id: "test-distinct-id",
            mode: "interactive",
          },
          acpSessionId: "session-1",
          acpConnection: { cleanup: vi.fn().mockResolvedValue(undefined) },
          clientConnection: {},
          sseController: null,
          deviceInfo: { type: "cloud" },
          logWriter: {
            appendRawLine: vi.fn(),
            flush: vi.fn().mockResolvedValue(undefined),
          },
          permissionMode: "default",
          hasDesktopConnected: false,
        };

        const token = createToken();

        const response = await testServer.app.fetch(
          new Request(`http://localhost:${port}/events`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
        );

        expect(response.status).toBe(200);
        expect(response.body).not.toBeNull();
        reader = response.body?.getReader() ?? null;
        expect(reader).not.toBeNull();
        if (!reader) {
          throw new Error("Expected SSE response body reader");
        }

        await vi.waitFor(
          () => expect(keepaliveCallback.current).not.toBeNull(),
          { timeout: 10_000, interval: 50 },
        );
        const emitKeepalive = keepaliveCallback.current;
        if (!emitKeepalive) {
          throw new Error("Expected keepalive callback to be registered");
        }
        emitKeepalive();

        const decoder = new TextDecoder();
        let streamText = "";
        for (let attempts = 0; attempts < 10; attempts++) {
          const { done, value } = await reader.read();
          if (done) break;
          streamText += decoder.decode(value, { stream: true });
          if (streamText.includes(": keepalive\n\n")) break;
        }

        expect(streamText).toContain(": keepalive\n\n");
        expect(streamText).not.toContain('"type":"keepalive"');
      } finally {
        await reader?.cancel();
        server = undefined;
        setIntervalSpy.mockRestore();
      }
    }, 30000);
  });

  describe("POST /command", () => {
    it("returns 401 without authorization", async () => {
      await createServer().start();

      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "user_message",
          params: { content: "test" },
        }),
      });

      expect(response.status).toBe(401);
    }, 20000);

    it("returns 400 when run_id does not match active session", async () => {
      await createServer().start();
      const token = createToken({ run_id: "different-run-id" });

      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "user_message",
          params: { content: "test" },
        }),
      });

      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toBe("No active session for this run");
    }, 20000);

    it("accepts structured user_message content", async () => {
      await createServer().start();
      const token = createToken({ run_id: "different-run-id" });

      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "user_message",
          params: {
            content: [{ type: "text", text: "test" }],
          },
        }),
      });

      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toBe("No active session for this run");
    }, 20000);

    it("accepts artifact-only user_message payloads", async () => {
      await createServer().start();
      const token = createToken({ run_id: "different-run-id" });

      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "user_message",
          params: {
            artifacts: [
              {
                id: "artifact-1",
                name: "test.txt",
                storage_path: "tasks/artifacts/test.txt",
              },
            ],
          },
        }),
      });

      expect(response.status).toBe(400);
      const body = await response.json();
      expect(body.error).toBe("No active session for this run");
    }, 20000);

    it("continues a cloud task after a manual compact command", async () => {
      const s = createServer();
      await s.start();
      const broadcastEvent = vi.fn();
      let serverInternals!: {
        session: { clientConnection: { prompt: typeof prompt } };
        broadcastEvent: typeof broadcastEvent;
        handleAcpTransportMessage(message: unknown): void;
      };
      const prompt = vi.fn(async (_params: { prompt: ContentBlock[] }) => {
        serverInternals.handleAcpTransportMessage({
          jsonrpc: "2.0",
          method: POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
          params: { sessionId: "session-1", stopReason: "end_turn" },
        });
        return { stopReason: "end_turn" };
      });
      serverInternals = s as unknown as typeof serverInternals;
      serverInternals.session.clientConnection.prompt = prompt;
      serverInternals.broadcastEvent = broadcastEvent;

      const token = createToken();
      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "compact-and-continue",
          method: "user_message",
          params: {
            content:
              "/compact Continue with the task using the question tool and plan.",
          },
        }),
      });

      expect(response.status).toBe(200);
      const body = (await response.json()) as {
        result?: { stopReason?: string };
      };
      expect(body.result?.stopReason).toBe("end_turn");
      expect(prompt).toHaveBeenCalledTimes(2);
      expect(prompt.mock.calls[0]?.[0].prompt).toEqual([
        {
          type: "text",
          text: "/compact Continue with the task using the question tool and plan.",
        },
      ]);
      expect(prompt.mock.calls[1]?.[0].prompt).toEqual([
        {
          type: "text",
          text: expect.stringContaining("Continue working on the task"),
          _meta: { ui: { hidden: true } },
        },
      ]);
      const turnCompleteEvents = broadcastEvent.mock.calls.filter(
        ([event]) =>
          (event as { notification?: { method?: string } }).notification
            ?.method === POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      );
      expect(turnCompleteEvents).toHaveLength(1);
    }, 20000);

    it("retries only the continuation after compact follow-up failure", async () => {
      const s = createServer();
      await s.start();
      const prompt = vi
        .fn(async (_params: { prompt: ContentBlock[] }) => ({
          stopReason: "end_turn",
        }))
        .mockResolvedValueOnce({ stopReason: "end_turn" })
        .mockRejectedValueOnce(new Error("sdk connection lost"));
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
      };
      serverInternals.session.clientConnection.prompt = prompt;

      const token = createToken();
      const send = async () =>
        fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: "compact-retry",
            method: "user_message",
            params: {
              content: "/compact Continue the task.",
              messageId: "compact-retry",
            },
          }),
        });

      const first = await send();
      expect(first.status).toBe(200);
      expect(prompt).toHaveBeenCalledTimes(2);

      const retry = await send();
      expect(retry.status).toBe(200);
      expect(prompt).toHaveBeenCalledTimes(3);
      expect(prompt.mock.calls[0]?.[0].prompt[0]).toMatchObject({
        type: "text",
        text: "/compact Continue the task.",
      });
      expect(prompt.mock.calls[1]?.[0].prompt[0]).toMatchObject({
        type: "text",
        text: expect.stringContaining("Continue working on the task"),
      });
      expect(prompt.mock.calls[2]?.[0].prompt[0]).toMatchObject({
        type: "text",
        text: expect.stringContaining("Continue working on the task"),
      });
    }, 20000);

    it("rewrites a bundled local skill slash command before sending the prompt", async () => {
      const skillDefinition = [
        "---",
        "name: local-test-skill",
        "description: Test skill",
        "---",
        "",
        "Reply with LOCAL_SKILL_MARKER from the bundled skill.",
      ].join("\n");
      const bundle = zipSync({
        "SKILL.md": new TextEncoder().encode(skillDefinition),
      });
      const checksum = createHash("sha256")
        .update(Buffer.from(bundle))
        .digest("hex");

      const s = createServer();
      await s.start();
      const prompt = vi.fn(
        async (_params: {
          prompt: ContentBlock[];
          _meta?: Record<string, unknown>;
        }) => ({ stopReason: "cancelled" }) as { stopReason: string },
      );
      const downloadArtifact = vi.fn(async () => exactArrayBuffer(bundle));
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
        posthogAPI: { downloadArtifact: typeof downloadArtifact };
      };
      serverInternals.session.clientConnection.prompt = prompt;
      serverInternals.posthogAPI.downloadArtifact = downloadArtifact;

      const token = createToken();
      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "skill-command",
          method: "user_message",
          params: {
            content: "/local-test-skill with context",
            artifacts: [
              {
                id: "skill-artifact-1",
                name: "local-test-skill.zip",
                type: "skill_bundle",
                source: "posthog_code_skill",
                storage_path: "tasks/artifacts/local-test-skill.zip",
                content_type: "application/zip",
                metadata: {
                  skill_name: "local-test-skill",
                  skill_source: "user",
                  content_sha256: checksum,
                  bundle_format: "zip",
                  schema_version: 1,
                },
              },
            ],
          },
        }),
      });

      expect(response.status).toBe(200);
      const body = (await response.json()) as {
        result?: { stopReason?: string };
      };
      expect(body.result?.stopReason).toBe("cancelled");
      expect(downloadArtifact).toHaveBeenCalledWith(
        "test-task-id",
        "test-run-id",
        "tasks/artifacts/local-test-skill.zip",
      );
      expect(prompt).toHaveBeenCalledOnce();

      const sentPrompt = prompt.mock.calls[0]?.[0].prompt;
      const sentMeta = prompt.mock.calls[0]?.[0]._meta;
      const sentText = sentPrompt?.find(
        (block): block is Extract<ContentBlock, { type: "text" }> =>
          block.type === "text",
      )?.text;

      expect(sentText).toBe("/local-test-skill with context");
      expect(sentMeta?.localSkillContext).toContain(
        'local skill "/local-test-skill"',
      );
      expect(sentMeta?.localSkillContext).toContain("LOCAL_SKILL_MARKER");
      expect(sentMeta?.localSkillContext).toContain("with context");
      expect(sentMeta?.localSkillName).toBe("local-test-skill");
    }, 20000);

    it("lists co-installed dependency skills with their paths in the skill context", async () => {
      const makeBundle = (name: string, body: string) =>
        zipSync({
          "SKILL.md": new TextEncoder().encode(
            [
              "---",
              `name: ${name}`,
              `description: ${name}`,
              "---",
              "",
              body,
            ].join("\n"),
          ),
        });
      const invokedBundle = makeBundle(
        "parent-skill",
        "Use /dep-skill for the review step.",
      );
      const depBundle = makeBundle("dep-skill", "Dependency instructions.");
      const checksumOf = (bundle: Uint8Array) =>
        createHash("sha256").update(Buffer.from(bundle)).digest("hex");

      const s = createServer();
      await s.start();
      const prompt = vi.fn(
        async (_params: {
          prompt: ContentBlock[];
          _meta?: Record<string, unknown>;
        }) => ({ stopReason: "cancelled" }) as { stopReason: string },
      );
      const downloadArtifact = vi.fn(
        async (_taskId: string, _runId: string, storagePath: string) =>
          exactArrayBuffer(
            storagePath.includes("dep-skill") ? depBundle : invokedBundle,
          ),
      );
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
        posthogAPI: { downloadArtifact: typeof downloadArtifact };
      };
      serverInternals.session.clientConnection.prompt = prompt;
      serverInternals.posthogAPI.downloadArtifact = downloadArtifact;

      const makeArtifact = (
        id: string,
        name: string,
        bundle: Uint8Array,
      ): Record<string, unknown> => ({
        id,
        name: `${name}.zip`,
        type: "skill_bundle",
        source: "posthog_code_skill",
        storage_path: `tasks/artifacts/${name}.zip`,
        content_type: "application/zip",
        metadata: {
          skill_name: name,
          skill_source: "user",
          content_sha256: checksumOf(bundle),
          bundle_format: "zip",
          schema_version: 1,
        },
      });

      const token = createToken();
      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "skill-command-deps",
          method: "user_message",
          params: {
            content: "/parent-skill run it",
            artifacts: [
              makeArtifact(
                "skill-artifact-parent",
                "parent-skill",
                invokedBundle,
              ),
              makeArtifact("skill-artifact-dep", "dep-skill", depBundle),
            ],
          },
        }),
      });

      expect(response.status).toBe(200);
      expect(prompt).toHaveBeenCalledOnce();

      const sentMeta = prompt.mock.calls[0]?.[0]._meta;
      const context = sentMeta?.localSkillContext as string;
      expect(sentMeta?.localSkillName).toBe("parent-skill");
      expect(context).toContain('local skill "/parent-skill"');
      expect(context).toContain("Other local skills installed for this run");
      expect(context).toMatch(/- \/dep-skill: \S*dep-skill/);
    }, 20000);

    it("announces mid-message skill mentions via localSkillContext without a skill name", async () => {
      const makeBundle = (name: string, body: string) =>
        zipSync({
          "SKILL.md": new TextEncoder().encode(
            [
              "---",
              `name: ${name}`,
              `description: ${name}`,
              "---",
              "",
              body,
            ].join("\n"),
          ),
        });
      const mentionedBundle = makeBundle(
        "mentioned-skill",
        "MENTIONED_SKILL_MARKER instructions.",
      );
      const prefixBundle = makeBundle("mentioned", "PREFIX_SKILL_MARKER body.");
      const checksumOf = (bundle: Uint8Array) =>
        createHash("sha256").update(Buffer.from(bundle)).digest("hex");

      const s = createServer();
      await s.start();
      const prompt = vi.fn(
        async (_params: {
          prompt: ContentBlock[];
          _meta?: Record<string, unknown>;
        }) => ({ stopReason: "cancelled" }) as { stopReason: string },
      );
      const downloadArtifact = vi.fn(
        async (_taskId: string, _runId: string, storagePath: string) =>
          exactArrayBuffer(
            storagePath.includes("mentioned-skill")
              ? mentionedBundle
              : prefixBundle,
          ),
      );
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
        posthogAPI: { downloadArtifact: typeof downloadArtifact };
      };
      serverInternals.session.clientConnection.prompt = prompt;
      serverInternals.posthogAPI.downloadArtifact = downloadArtifact;

      const makeArtifact = (
        id: string,
        name: string,
        bundle: Uint8Array,
      ): Record<string, unknown> => ({
        id,
        name: `${name}.zip`,
        type: "skill_bundle",
        source: "posthog_code_skill",
        storage_path: `tasks/artifacts/${name}.zip`,
        content_type: "application/zip",
        metadata: {
          skill_name: name,
          skill_source: "user",
          content_sha256: checksumOf(bundle),
          bundle_format: "zip",
          schema_version: 1,
        },
      });

      const token = createToken();
      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "skill-mid-message",
          method: "user_message",
          params: {
            content: "please use /mentioned-skill on the diff",
            artifacts: [
              makeArtifact(
                "skill-artifact-mentioned",
                "mentioned-skill",
                mentionedBundle,
              ),
              makeArtifact("skill-artifact-prefix", "mentioned", prefixBundle),
            ],
          },
        }),
      });

      expect(response.status).toBe(200);
      expect(prompt).toHaveBeenCalledOnce();

      const sentPrompt = prompt.mock.calls[0]?.[0].prompt;
      const sentMeta = prompt.mock.calls[0]?.[0]._meta;
      const context = sentMeta?.localSkillContext as string;
      // not a bare invocation, so nothing to strip and no localSkillName
      expect(sentMeta?.localSkillName).toBeUndefined();
      expect(context).toContain("MENTIONED_SKILL_MARKER");
      // "mentioned" is a prefix of "/mentioned-skill" but was not itself
      // mentioned: listed by path, not inlined
      expect(context).not.toContain("PREFIX_SKILL_MARKER");
      expect(context).toMatch(/- \/mentioned: \S*mentioned/);
      const sentText = sentPrompt?.find(
        (block): block is Extract<ContentBlock, { type: "text" }> =>
          block.type === "text",
      )?.text;
      expect(sentText).toBe("please use /mentioned-skill on the diff");
    }, 20000);

    it("ignores a redelivered user_message whose messageId was already accepted", async () => {
      const s = createServer();
      await s.start();
      const prompt = vi.fn(async () => ({ stopReason: "end_turn" }));
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
      };
      serverInternals.session.clientConnection.prompt = prompt;

      const token = createToken();
      const send = async (messageId: string | undefined) => {
        const response = await fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: messageId ?? "no-id",
            method: "user_message",
            params: {
              content: "do the thing",
              ...(messageId ? { messageId } : {}),
            },
          }),
        });
        expect(response.status).toBe(200);
        return (await response.json()) as {
          result?: { stopReason?: string; duplicate?: boolean };
        };
      };

      const first = await send("m-1");
      expect(first.result?.stopReason).toBe("end_turn");
      expect(prompt).toHaveBeenCalledTimes(1);

      const redelivery = await send("m-1");
      expect(redelivery.result?.duplicate).toBe(true);
      expect(redelivery.result?.stopReason).toBe("duplicate_delivery");
      expect(prompt).toHaveBeenCalledTimes(1);

      const distinct = await send("m-2");
      expect(distinct.result?.stopReason).toBe("end_turn");
      expect(prompt).toHaveBeenCalledTimes(2);

      const anonymousFirst = await send(undefined);
      const anonymousSecond = await send(undefined);
      expect(anonymousFirst.result?.stopReason).toBe("end_turn");
      expect(anonymousSecond.result?.stopReason).toBe("end_turn");
      expect(prompt).toHaveBeenCalledTimes(4);
    }, 20000);

    it("steers an active turn without emitting a separate turn completion", async () => {
      const s = createServer();
      await s.start();
      const prompt = vi.fn(async () => ({
        stopReason: "end_turn",
        _meta: { steer: true },
      }));
      const broadcastTurnComplete = vi.fn();
      const resetTurnMessages = vi.fn();
      const serverInternals = s as unknown as {
        activeOwnedTurnCount: number;
        broadcastTurnComplete: typeof broadcastTurnComplete;
        session: {
          clientConnection: { prompt: typeof prompt };
          logWriter: { resetTurnMessages: typeof resetTurnMessages };
        };
      };
      serverInternals.activeOwnedTurnCount = 1;
      serverInternals.broadcastTurnComplete = broadcastTurnComplete;
      serverInternals.session.clientConnection.prompt = prompt;
      serverInternals.session.logWriter.resetTurnMessages = resetTurnMessages;

      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${createToken()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "steer-1",
          method: "user_message",
          params: { content: "change direction", steer: true },
        }),
      });

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toMatchObject({
        result: { stopReason: "steered", steered: true },
      });
      expect(prompt).toHaveBeenCalledWith(
        expect.objectContaining({
          _meta: expect.objectContaining({ steer: true }),
        }),
      );
      expect(broadcastTurnComplete).not.toHaveBeenCalled();
      expect(resetTurnMessages).not.toHaveBeenCalled();
    }, 20000);

    it("declines steering without blocking on a fallback normal turn", async () => {
      const s = createServer();
      await s.start();
      const prompt = vi.fn();
      const broadcastTurnComplete = vi.fn();
      const resetTurnMessages = vi.fn();
      const serverInternals = s as unknown as {
        activeOwnedTurnCount: number;
        broadcastTurnComplete: typeof broadcastTurnComplete;
        session: {
          clientConnection: { prompt: typeof prompt };
          logWriter: { resetTurnMessages: typeof resetTurnMessages };
        };
      };
      serverInternals.activeOwnedTurnCount = 1;
      prompt.mockImplementationOnce(async () => {
        serverInternals.activeOwnedTurnCount = 0;
        return { stopReason: "end_turn", _meta: { steer: false } };
      });
      serverInternals.broadcastTurnComplete = broadcastTurnComplete;
      serverInternals.session.clientConnection.prompt = prompt;
      serverInternals.session.logWriter.resetTurnMessages = resetTurnMessages;

      const response = await fetch(`http://localhost:${port}/command`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${createToken()}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: "steer-race",
          method: "user_message",
          params: { content: "continue normally", steer: true },
        }),
      });

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toMatchObject({
        result: { stopReason: "steer_declined", steered: false },
      });
      expect(prompt).toHaveBeenCalledTimes(1);
      expect(prompt.mock.calls[0]?.[0]).toEqual(
        expect.objectContaining({
          _meta: expect.objectContaining({ steer: true }),
        }),
      );
      expect(resetTurnMessages).not.toHaveBeenCalled();
      expect(broadcastTurnComplete).not.toHaveBeenCalled();
    }, 20000);

    it("redelivers a messageId whose first delivery failed before producing a turn", async () => {
      const s = createServer();
      await s.start();
      const prompt = vi
        .fn(async () => ({ stopReason: "end_turn" }))
        .mockRejectedValueOnce(new Error("sdk connection lost"));
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
      };
      serverInternals.session.clientConnection.prompt = prompt;

      const token = createToken();
      const send = async () =>
        fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: "m-err",
            method: "user_message",
            params: { content: "do the thing", messageId: "m-err" },
          }),
        });

      await send();
      expect(prompt).toHaveBeenCalledTimes(1);

      const retry = await send();
      expect(retry.status).toBe(200);
      const body = (await retry.json()) as {
        result?: { stopReason?: string; duplicate?: boolean };
      };
      expect(body.result?.duplicate).toBeUndefined();
      expect(body.result?.stopReason).toBe("end_turn");
      expect(prompt).toHaveBeenCalledTimes(2);
    }, 20000);

    it("keeps a recoverable delivery committed across an ambiguous retry", async () => {
      const s = createServer();
      await s.start();
      const prompt = vi
        .fn()
        .mockRejectedValue(new Error("API Error: The operation timed out."));
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } };
      };
      serverInternals.session.clientConnection.prompt = prompt;

      const token = createToken();
      const send = async (requestId: string) =>
        fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: requestId,
            method: "user_message",
            params: {
              content: "do the thing",
              messageId: "m-recoverable",
            },
          }),
        });

      const first = await send("first-attempt");
      await expect(first.json()).resolves.toMatchObject({
        result: { stopReason: "error_recoverable" },
      });
      expect(prompt).toHaveBeenCalledTimes(1);

      const retry = await send("ambiguous-retry");
      await expect(retry.json()).resolves.toMatchObject({
        result: { stopReason: "duplicate_delivery", duplicate: true },
      });
      expect(prompt).toHaveBeenCalledTimes(1);
    }, 20000);

    it("shares a failed in-flight messageId outcome with concurrent retries", async () => {
      const s = createServer();
      await s.start();
      let rejectFirstDelivery!: (error: Error) => void;
      const prompt = vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise((_resolve, reject) => {
              rejectFirstDelivery = reject;
            }),
        )
        .mockResolvedValueOnce({ stopReason: "end_turn" });
      const serverInternals = s as unknown as {
        logger: { info: (...args: unknown[]) => void };
        session: { clientConnection: { prompt: typeof prompt } };
      };
      serverInternals.session.clientConnection.prompt = prompt;
      const infoLog = vi.spyOn(serverInternals.logger, "info");

      const token = createToken();
      const send = async (requestId: string) =>
        fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: requestId,
            method: "user_message",
            params: { content: "do the thing", messageId: "m-concurrent" },
          }),
        });

      const firstResponse = send("first-attempt");
      await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(1));

      let retrySettled = false;
      const retryResponse = send("concurrent-retry").finally(() => {
        retrySettled = true;
      });
      await vi.waitFor(() => {
        expect(infoLog).toHaveBeenCalledWith(
          "Awaiting in-flight user_message delivery",
          { messageId: "m-concurrent" },
        );
        expect(prompt).toHaveBeenCalledTimes(1);
        expect(retrySettled).toBe(false);
      });

      rejectFirstDelivery(new Error("sdk connection lost"));
      const [first, retry] = await Promise.all([firstResponse, retryResponse]);
      await expect(first.json()).resolves.toMatchObject({
        error: { message: "sdk connection lost" },
      });
      await expect(retry.json()).resolves.toMatchObject({
        error: { message: "sdk connection lost" },
      });
      expect(prompt).toHaveBeenCalledTimes(1);
    }, 20000);

    it("keeps an accepted messageId committed when teardown clears the active session", async () => {
      const s = createServer();
      await s.start();
      let finishPrompt!: (result: { stopReason: "end_turn" }) => void;
      const prompt = vi.fn(
        () =>
          new Promise<{ stopReason: "end_turn" }>((resolve) => {
            finishPrompt = resolve;
          }),
      );
      const serverInternals = s as unknown as {
        session: { clientConnection: { prompt: typeof prompt } } | null;
      };
      const acceptedSession = serverInternals.session;
      if (!acceptedSession) throw new Error("expected active test session");
      acceptedSession.clientConnection.prompt = prompt;

      const token = createToken();
      const send = async (requestId: string) =>
        fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: requestId,
            method: "user_message",
            params: { content: "do the thing", messageId: "m-teardown" },
          }),
        });

      const firstResponse = send("first-attempt");
      await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(1));

      serverInternals.session = null;
      finishPrompt({ stopReason: "end_turn" });
      const first = await firstResponse;
      await expect(first.json()).resolves.toMatchObject({
        result: { stopReason: "end_turn" },
      });

      serverInternals.session = acceptedSession;
      const retry = await send("retry");
      await expect(retry.json()).resolves.toMatchObject({
        result: { stopReason: "duplicate_delivery", duplicate: true },
      });
      expect(prompt).toHaveBeenCalledTimes(1);
    }, 20000);

    // Shared plumbing for the relay-echo tests: install a controllable
    // prompt, stub the log writer so relayAgentResponse has an answer to
    // relay, and spy on the relay_message client call.
    const setupRelayEchoServer = async (
      prompt: () => Promise<{ stopReason: string }>,
    ) => {
      const s = createServer();
      await s.start();
      const serverInternals = s as unknown as {
        session: {
          clientConnection: { prompt: typeof prompt };
          logWriter: {
            getFullAgentResponse: (runId: string) => string | undefined;
            getAgentResponseParts: (runId: string) => string[];
          };
        };
        posthogAPI: PostHogAPIClient;
      };
      serverInternals.session.clientConnection.prompt = prompt;
      vi.spyOn(
        serverInternals.session.logWriter,
        "getFullAgentResponse",
      ).mockReturnValue("final answer");
      vi.spyOn(
        serverInternals.session.logWriter,
        "getAgentResponseParts",
      ).mockReturnValue(["final answer"]);
      const relaySpy = vi
        .spyOn(serverInternals.posthogAPI, "relayMessage")
        .mockResolvedValue(undefined);

      const token = createToken();
      const send = (messageId?: string) =>
        fetch(`http://localhost:${port}/command`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            jsonrpc: "2.0",
            id: messageId ?? "no-id",
            method: "user_message",
            params: {
              content: "do the thing",
              ...(messageId ? { messageId } : {}),
            },
          }),
        });

      return { relaySpy, send };
    };

    it("echoes each turn's own initiating messageId on relay_message", async () => {
      const pendingTurns: Array<(result: { stopReason: string }) => void> = [];
      const prompt = vi.fn(
        () =>
          new Promise<{ stopReason: string }>((resolve) => {
            pendingTurns.push(resolve);
          }),
      );
      const { relaySpy, send } = await setupRelayEchoServer(prompt);

      // The second message lands while the first turn is still in flight;
      // each relay carries its own sender's id, not the first turn's.
      const first = send("m-first");
      await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(1));
      const second = send("m-second");
      await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(2));

      pendingTurns[0]({ stopReason: "end_turn" });
      await first;
      await vi.waitFor(() => expect(relaySpy).toHaveBeenCalledTimes(1));
      expect(relaySpy.mock.calls[0][4]).toBe("m-first");

      pendingTurns[1]({ stopReason: "end_turn" });
      await second;
      await vi.waitFor(() => expect(relaySpy).toHaveBeenCalledTimes(2));
      expect(relaySpy.mock.calls[1][4]).toBe("m-second");

      // A message without an id relays without correlation (backward
      // compatible with backends that don't know message_id).
      relaySpy.mockClear();
      const anonymous = send(undefined);
      await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(3));
      pendingTurns[2]({ stopReason: "end_turn" });
      await anonymous;
      await vi.waitFor(() => expect(relaySpy).toHaveBeenCalledTimes(1));
      expect(relaySpy.mock.calls[0][4]).toBeUndefined();
    }, 20000);

    it("does not leak a failed turn's messageId into the next turn", async () => {
      const prompt = vi
        .fn(async () => ({ stopReason: "end_turn" }))
        .mockRejectedValueOnce(new Error("sdk connection lost"));
      const { relaySpy, send } = await setupRelayEchoServer(prompt);

      await send("m-fail");
      expect(relaySpy).not.toHaveBeenCalled();

      await send("m-next");
      await vi.waitFor(() => expect(relaySpy).toHaveBeenCalledTimes(1));
      expect(relaySpy.mock.calls[0][4]).toBe("m-next");
    }, 20000);
  });

  describe("404 handling", () => {
    it("returns 404 for unknown routes", async () => {
      await createServer().start();

      const response = await fetch(`http://localhost:${port}/unknown`);
      const body = await response.json();

      expect(response.status).toBe(404);
      expect(body.error).toBe("Not found");
    }, 20000);
  });

  describe("session lifecycle", () => {
    it("emits _posthog/run_started after session initialization", async () => {
      await createServer().start();

      // The notification is persisted via `logWriter.appendRawLine` which the
      // mock backend's append_log handler captures into `appendLogCalls`.
      await vi.waitFor(
        () => {
          const allEntries = appendLogCalls.flat() as Array<{
            type?: string;
            notification?: {
              method?: string;
              params?: Record<string, unknown>;
            };
          }>;
          const runStarted = allEntries.find(
            (e) => e?.notification?.method === "_posthog/run_started",
          );
          expect(runStarted).toBeDefined();
          expect(runStarted?.notification?.params).toMatchObject({
            runId: "test-run-id",
            taskId: "test-task-id",
            steering: "native",
          });
          // Agent reports its semver so clients can gate UI features
          // against agent capabilities (e.g. `>=0.40.1`). The exact value
          // is whatever the agent's package.json was at build time.
          expect(typeof runStarted?.notification?.params?.agentVersion).toBe(
            "string",
          );
          expect(
            (runStarted?.notification?.params?.agentVersion as string).length,
          ).toBeGreaterThan(0);
        },
        { timeout: 15000, interval: 100 },
      );
    }, 30000);

    it("emits a completed _posthog/progress for the agent step after session initialization", async () => {
      await createServer().start();

      // Resolves the setup card's "agent" step on the agent-proxy read leg,
      // where the orchestrator's Django-only progress event never arrives.
      await vi.waitFor(
        () => {
          const allEntries = appendLogCalls.flat() as Array<{
            notification?: {
              method?: string;
              params?: Record<string, unknown>;
            };
          }>;
          const agentProgress = allEntries.find(
            (e) =>
              e?.notification?.method === "_posthog/progress" &&
              e?.notification?.params?.step === "agent",
          );
          expect(agentProgress).toBeDefined();
          expect(agentProgress?.notification?.params).toMatchObject({
            group: "setup:test-run-id",
            step: "agent",
            status: "completed",
          });
          expect(typeof agentProgress?.notification?.params?.label).toBe(
            "string",
          );
        },
        { timeout: 15000, interval: 100 },
      );
    }, 30000);
  });

  describe("getInitialPromptOverride", () => {
    it("returns override string from run state", () => {
      const s = createServer();
      const run = {
        state: { initial_prompt_override: "do something else" },
      } as unknown as TaskRun;
      const result = (s as unknown as TestableServer).getInitialPromptOverride(
        run,
      );
      expect(result).toBe("do something else");
    });

    it("returns null when override is absent", () => {
      const s = createServer();
      const run = { state: {} } as unknown as TaskRun;
      const result = (s as unknown as TestableServer).getInitialPromptOverride(
        run,
      );
      expect(result).toBeNull();
    });

    it("returns null for whitespace-only override", () => {
      const s = createServer();
      const run = {
        state: { initial_prompt_override: "  " },
      } as unknown as TaskRun;
      const result = (s as unknown as TestableServer).getInitialPromptOverride(
        run,
      );
      expect(result).toBeNull();
    });

    it("returns null for non-string override", () => {
      const s = createServer();
      const run = {
        state: { initial_prompt_override: 42 },
      } as unknown as TaskRun;
      const result = (s as unknown as TestableServer).getInitialPromptOverride(
        run,
      );
      expect(result).toBeNull();
    });

    it("removes pending prompt keys when clearing initial prompt state", async () => {
      const s = createServer();
      const updateTaskRun = vi
        .spyOn(
          (
            s as unknown as {
              posthogAPI: {
                updateTaskRun: (...args: unknown[]) => Promise<unknown>;
              };
            }
          ).posthogAPI,
          "updateTaskRun",
        )
        .mockResolvedValue({} as never);
      const run = {
        id: "test-run-id",
        task: "test-task-id",
        state: {
          sandbox_url: "https://sandbox.example.com",
          sandbox_connect_token: "token",
          pending_user_message: "read this",
          pending_user_artifact_ids: ["artifact-1"],
          pending_user_message_ts: "123.456",
        },
      } as unknown as TaskRun;

      const nextState = (
        s as unknown as TestableServer
      ).getClearedPendingUserState(run);
      expect(nextState).toEqual([
        "pending_user_message",
        "pending_user_artifact_ids",
        "pending_user_message_ts",
      ]);

      await (s as unknown as TestableServer).clearPendingInitialPromptState(
        {
          run_id: "test-run-id",
          task_id: "test-task-id",
          team_id: 1,
          user_id: 1,
          distinct_id: "test-distinct-id",
          mode: "interactive",
        },
        run,
      );

      expect(updateTaskRun).toHaveBeenCalledWith(
        "test-task-id",
        "test-run-id",
        {
          state_remove_keys: [
            "pending_user_message",
            "pending_user_artifact_ids",
            "pending_user_message_ts",
          ],
        },
      );
    });
  });

  describe("resume prompt display", () => {
    it("hides synthetic resume context while keeping the pending user message visible", async () => {
      const s = createServer() as unknown as {
        resumeState: ResumeState | null;
        session: {
          payload: JwtPayload;
          acpSessionId: string;
          clientConnection: {
            prompt: ReturnType<typeof vi.fn>;
          };
          logWriter: {
            resetTurnMessages: ReturnType<typeof vi.fn>;
            appendRawLine: ReturnType<typeof vi.fn>;
            flushAll: ReturnType<typeof vi.fn>;
          };
          sseController: null;
          deviceInfo: { type: "cloud"; name: string };
          permissionMode: PermissionMode;
          hasDesktopConnected: boolean;
        };
        sendResumeMessage(
          payload: JwtPayload,
          taskRun: TaskRun | null,
        ): Promise<void>;
      };
      const payload: JwtPayload = {
        run_id: "test-run-id",
        task_id: "test-task-id",
        team_id: 1,
        user_id: 1,
        distinct_id: "test-distinct-id",
        mode: "interactive",
      };
      const prompt = vi.fn(async () => ({ stopReason: "cancelled" }));
      s.session = {
        payload,
        acpSessionId: "acp-session",
        clientConnection: { prompt },
        logWriter: {
          resetTurnMessages: vi.fn(),
          appendRawLine: vi.fn(),
          flushAll: vi.fn(),
        },
        sseController: null,
        deviceInfo: { type: "cloud", name: "test-sandbox" },
        permissionMode: "bypassPermissions",
        hasDesktopConnected: false,
      };
      s.resumeState = {
        conversation: [
          { role: "user", content: [{ type: "text", text: "old request" }] },
          {
            role: "assistant",
            content: [{ type: "text", text: "old answer" }],
          },
        ],
        latestGitCheckpoint: null,
        interrupted: false,
        logEntryCount: 2,
        sessionId: "prior-session",
      };

      await s.sendResumeMessage(
        payload,
        createTaskRun({
          id: "test-run-id",
          task: "test-task-id",
          state: {
            pending_user_message: "visible follow-up",
            pending_user_message_ts: "123.456",
          },
        }),
      );

      const [{ prompt: promptBlocks }] = prompt.mock.calls[0] as unknown as [
        { prompt: ContentBlock[] },
      ];
      const visibleText = promptBlocks
        .filter(
          (block) =>
            block.type === "text" &&
            !(
              (block as { _meta?: { ui?: { hidden?: boolean } } })._meta?.ui
                ?.hidden === true
            ),
        )
        .map((block) => (block as { text: string }).text);

      expect(promptBlocks[0]).toMatchObject({
        type: "text",
        _meta: { ui: { hidden: true } },
      });
      expect((promptBlocks[0] as { text: string }).text).toContain(
        "You are resuming a previous conversation",
      );
      expect(visibleText).toEqual(["visible follow-up"]);
      expect(promptBlocks.at(-1)).toMatchObject({
        type: "text",
        _meta: { ui: { hidden: true } },
      });
    });
  });

  describe("runtime adapter selection", () => {
    it("defaults to claude when no runtime adapter is configured", () => {
      const s = createServer();

      expect((s as unknown as TestableServer).getRuntimeAdapter()).toBe(
        "claude",
      );
    });

    it("uses codex when the runtime adapter is configured", () => {
      const s = createServer({ runtimeAdapter: "codex" });

      expect((s as unknown as TestableServer).getRuntimeAdapter()).toBe(
        "codex",
      );
    });

    it("flattens append-style prompts into plain codex instructions", () => {
      const s = createServer({
        claudeCode: {
          systemPrompt: {
            type: "preset",
            preset: "claude_code",
            append: "User codex instructions",
          },
        },
      });

      const sessionPrompt = (
        s as unknown as TestableServer
      ).buildSessionSystemPrompt("https://github.com/PostHog/code/pull/1");

      expect(typeof sessionPrompt).toBe("object");
      expect(
        (s as unknown as TestableServer).buildCodexInstructions(sessionPrompt),
      ).toContain("User codex instructions");
      expect(
        (s as unknown as TestableServer).buildCodexInstructions(sessionPrompt),
      ).toContain("Cloud Task Execution");
    });
  });

  describe("buildClaudeCodeSessionMeta", () => {
    it("sends claude reasoning effort even when no plugins are configured", () => {
      const s = createServer({ reasoningEffort: "high" });

      const meta = (s as unknown as TestableServer).buildClaudeCodeSessionMeta(
        "claude",
      );

      expect(meta?.claudeCode.options).toEqual({ effort: "high" });
    });

    it("does not send claudeCode effort for codex runs", () => {
      const s = createServer({ reasoningEffort: "high" });

      const meta = (s as unknown as TestableServer).buildClaudeCodeSessionMeta(
        "codex",
      );

      expect(meta).toBeUndefined();
    });

    it("returns undefined when neither plugins nor effort are set", () => {
      const s = createServer();

      const meta = (s as unknown as TestableServer).buildClaudeCodeSessionMeta(
        "claude",
      );

      expect(meta).toBeUndefined();
    });

    it("includes both plugins and effort for claude runs", () => {
      const s = createServer({
        reasoningEffort: "medium",
        claudeCode: { plugins: [{ type: "local", path: "/tmp/plugin" }] },
      });

      const meta = (s as unknown as TestableServer).buildClaudeCodeSessionMeta(
        "claude",
      );

      expect(meta?.claudeCode.options).toEqual({
        plugins: [{ type: "local", path: "/tmp/plugin" }],
        effort: "medium",
      });
    });

    it("returns only plugins when effort is not set", () => {
      const s = createServer({
        claudeCode: { plugins: [{ type: "local", path: "/tmp/plugin" }] },
      });

      const meta = (s as unknown as TestableServer).buildClaudeCodeSessionMeta(
        "claude",
      );

      expect(meta?.claudeCode.options).toEqual({
        plugins: [{ type: "local", path: "/tmp/plugin" }],
      });
    });
  });

  describe("native resume", () => {
    it("restores persisted Codex goals only for fresh Codex sessions", () => {
      const s = createServer() as unknown as TestableServer;
      const goal = { objective: "Ship the fix", status: "paused" as const };
      s.resumeState = {
        conversation: [],
        latestGitCheckpoint: null,
        interrupted: false,
        logEntryCount: 1,
        sessionId: "prior-session",
        nativeGoal: goal,
      };

      expect(s.getNativeGoalForFreshSession("codex")).toEqual(goal);
      expect(s.getNativeGoalForFreshSession("claude")).toBeUndefined();
    });

    it.each([
      { retryOutcome: "succeeds", retryFails: false },
      { retryOutcome: "fails", retryFails: true },
    ])(
      "clears resume state when the fresh-session retry $retryOutcome",
      async ({ retryFails }) => {
        const s = createServer();
        await s.start();

        const prompts: ContentBlock[][] = [];
        const prompt = vi.fn(async (params: { prompt: ContentBlock[] }) => {
          prompts.push(params.prompt);
          if (prompts.length === 1) {
            throw new Error("Internal error: Prompt is too long");
          }
          if (retryFails) {
            throw new Error("Fresh-session retry failed");
          }
          return { stopReason: "end_turn" };
        });
        const newSession = vi.fn(async () => ({ sessionId: "fresh-session" }));

        const internals = s as unknown as {
          session: {
            acpSessionId: string;
            clientConnection: {
              prompt: typeof prompt;
              newSession: typeof newSession;
            };
          };
          resumeState: ResumeState | null;
          nativeResume: { sessionId: string; warm: boolean } | null;
          loadResumeState(
            taskId: string,
            resumeRunId: string,
            runId: string,
          ): Promise<void>;
          sendResumeContinuation(
            payload: JwtPayload,
            taskRun: TaskRun | null,
          ): Promise<void>;
        };
        internals.session.clientConnection.prompt = prompt;
        internals.session.clientConnection.newSession = newSession;
        internals.nativeResume = { sessionId: "prior-session", warm: true };
        internals.loadResumeState = vi.fn(async () => {
          internals.resumeState = {
            conversation: [
              {
                role: "user",
                content: [{ type: "text", text: "original task" }],
              },
              {
                role: "assistant",
                content: [{ type: "text", text: "progress so far" }],
              },
            ],
            latestGitCheckpoint: null,
            interrupted: false,
            logEntryCount: 2,
            sessionId: "prior-session",
          };
        });

        await internals.sendResumeContinuation(
          {
            task_id: "test-task-id",
            run_id: "test-run-id",
            team_id: 1,
            user_id: 1,
            distinct_id: "test-distinct-id",
            mode: "interactive",
          },
          createTaskRun({
            id: "test-run-id",
            state: { resume_from_run_id: "previous-run" },
          }),
        );

        expect(newSession).toHaveBeenCalledOnce();
        expect(internals.session.acpSessionId).toBe("fresh-session");
        expect(internals.resumeState).toBeNull();
        expect(internals.nativeResume).toBeNull();
        expect(prompts).toHaveLength(2);
        const retryText = prompts[1]
          .map((block) => ("text" in block ? block.text : ""))
          .join("\n");
        expect(retryText).toContain("progress so far");
      },
      20000,
    );

    it("hydrates cold sessions from S3 logs instead of cached resume conversation", async () => {
      const originalConfigDir = process.env.CLAUDE_CONFIG_DIR;
      process.env.CLAUDE_CONFIG_DIR = join(repo.path, ".claude-test");

      try {
        const s = createServer() as unknown as NativeResumeTestServer;
        s.resumeState = {
          conversation: [
            {
              role: "user",
              content: [{ type: "text", text: "continue" }],
            },
            {
              role: "assistant",
              content: [{ type: "text", text: "visible answer only" }],
            },
          ],
          latestGitCheckpoint: null,
          interrupted: false,
          logEntryCount: 3,
          sessionId: "prior-session",
        };

        const posthogAPI = createMockApiClient();
        (posthogAPI.getTaskRun as ReturnType<typeof vi.fn>).mockResolvedValue(
          createTaskRun({ id: "previous-run", log_url: "s3://logs" }),
        );
        (
          posthogAPI.fetchTaskRunLogs as ReturnType<typeof vi.fn>
        ).mockResolvedValue([
          sessionUpdateEntry("user_message", {
            content: { type: "text", text: "continue" },
          }),
          sessionUpdateEntry("agent_thought_chunk", {
            content: {
              type: "thinking",
              thinking: "preserve extended thinking",
            },
          }),
          sessionUpdateEntry("agent_message", {
            content: { type: "text", text: "visible answer" },
          }),
        ]);

        const result = await s.prepareNativeResume(
          {
            task_id: "test-task-id",
            run_id: "test-run-id",
            team_id: 1,
            user_id: 1,
            distinct_id: "test-distinct-id",
            mode: "interactive",
          },
          posthogAPI,
          createTaskRun({
            id: "test-run-id",
            state: { resume_from_run_id: "previous-run" },
          }),
          "claude",
          repo.path,
          "bypassPermissions",
        );

        expect(result).toEqual({ sessionId: "prior-session", warm: false });
        expect(posthogAPI.fetchTaskRunLogs).toHaveBeenCalledTimes(1);

        const jsonl = await readFile(
          getSessionJsonlPath("prior-session", repo.path),
          "utf-8",
        );
        const blocks = jsonl
          .trim()
          .split("\n")
          .flatMap((line) => {
            const parsed = JSON.parse(line) as {
              message?: { content?: unknown[] };
            };
            return parsed.message?.content ?? [];
          });

        expect(blocks).toContainEqual({
          type: "thinking",
          thinking: "preserve extended thinking",
        });
      } finally {
        if (originalConfigDir === undefined) {
          delete process.env.CLAUDE_CONFIG_DIR;
        } else {
          process.env.CLAUDE_CONFIG_DIR = originalConfigDir;
        }
      }
    });

    describe("codex", () => {
      const THREAD_ID = "0199a5c3-2f60-7b21-9c39-1d2e3f4a5b6c";
      let codexHome: string;

      const payload: JwtPayload = {
        task_id: "test-task-id",
        run_id: "test-run-id",
        team_id: 1,
        user_id: 1,
        distinct_id: "test-distinct-id",
        mode: "interactive",
      };

      const codexServer = (sessionId: string | null) => {
        const s = createServer() as unknown as NativeResumeTestServer;
        s.resumeState = {
          conversation: [
            { role: "user", content: [{ type: "text", text: "continue" }] },
          ],
          latestGitCheckpoint: null,
          interrupted: false,
          logEntryCount: 1,
          sessionId,
        };
        return s;
      };

      const prepare = (s: NativeResumeTestServer) =>
        s.prepareNativeResume(
          payload,
          createMockApiClient(),
          createTaskRun({
            id: "test-run-id",
            state: { resume_from_run_id: "previous-run" },
          }),
          "codex",
          repo.path,
          "auto",
        );

      beforeEach(() => {
        codexHome = join(repo.path, ".codex-test");
        vi.stubEnv("CODEX_HOME", codexHome);
      });

      afterEach(() => {
        vi.unstubAllEnvs();
      });

      it("resumes natively when the thread rollout survived in CODEX_HOME", async () => {
        const dir = join(codexHome, "sessions", "2026", "07", "07");
        await mkdir(dir, { recursive: true });
        await writeFile(
          join(dir, `rollout-2026-07-07T10-00-00-${THREAD_ID}.jsonl`),
          "",
        );

        await expect(prepare(codexServer(THREAD_ID))).resolves.toEqual({
          sessionId: THREAD_ID,
          warm: true,
        });
      });

      it.each([
        ["the thread state is gone", THREAD_ID],
        ["there is no prior session id", null],
      ])("falls back to summary resume when %s", async (_case, sessionId) => {
        await expect(prepare(codexServer(sessionId))).resolves.toBeNull();
      });
    });
  });

  describe("PR attribution", () => {
    const PR_URL = "https://github.com/PostHog/posthog.com/pull/17764";
    const payload: JwtPayload = {
      task_id: "t",
      run_id: "r",
      team_id: 1,
      user_id: 1,
      distinct_id: "d",
      mode: "interactive",
    };

    // The cloud sandbox frames a created PR's URL inside terminal output, on a
    // tool_call_update that carries no toolName/bashCommand — the case the old
    // detector missed. Attribution must work from the serialized update alone.
    const terminalUpdate = (url: string) => ({
      sessionUpdate: "tool_call_update",
      _meta: { terminal_output: `Creating draft pull request...\n${url}\n` },
    });

    type PrTestServer = {
      maybeAttachCreatedPr(
        p: JwtPayload,
        u: Record<string, unknown> | undefined,
      ): void;
      fetchPrAttribution(
        url: string,
      ): Promise<{ createdAt: string | null; author: string | null }>;
      fetchGhLogin(): Promise<string | null>;
      detectedPrUrl: string | null;
      posthogAPI: {
        getTaskRun: ReturnType<typeof vi.fn>;
        updateTaskRun: ReturnType<typeof vi.fn>;
      };
    };

    const justNow = () => new Date().toISOString();
    const longAgo = "2020-01-01T00:00:00Z";
    const GH_LOGIN = "run-owner";

    const setup = (
      prCreatedAt: string | null,
      prAuthor: string | null = GH_LOGIN,
    ): PrTestServer => {
      const s = createServer() as unknown as PrTestServer;
      s.fetchPrAttribution = vi.fn(async () => ({
        createdAt: prCreatedAt,
        author: prAuthor,
      }));
      s.fetchGhLogin = vi.fn(async () => GH_LOGIN);
      let storedOutput: Record<string, unknown> | null = null;
      s.posthogAPI = {
        getTaskRun: vi.fn(async () => ({ output: storedOutput })),
        updateTaskRun: vi.fn(
          async (
            _taskId: string,
            _runId: string,
            updates: { output: Record<string, unknown> },
          ) => {
            storedOutput = updates.output;
            return {};
          },
        ),
      };
      return s;
    };

    const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

    it("attributes a PR created just now from terminal output alone", async () => {
      const s = setup(justNow());
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      await flush();
      expect(s.posthogAPI.updateTaskRun).toHaveBeenCalledWith("t", "r", {
        output: { pr_url: PR_URL, pr_urls: [PR_URL] },
      });
      expect(s.detectedPrUrl).toBe(PR_URL);
    });

    it("does not attribute an older PR the run only viewed (e.g. on a long run)", async () => {
      const s = setup(longAgo);
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      await flush();
      expect(s.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
      expect(s.detectedPrUrl).toBeNull();
    });

    it("ignores updates with no PR URL", async () => {
      const s = setup(justNow());
      s.maybeAttachCreatedPr(payload, { sessionUpdate: "agent_thought_chunk" });
      await flush();
      expect(s.fetchPrAttribution).not.toHaveBeenCalled();
      expect(s.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
    });

    it("attributes once and looks up GitHub once across repeated updates", async () => {
      const s = setup(justNow());
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      await flush();
      expect(s.fetchPrAttribution).toHaveBeenCalledTimes(1);
      expect(s.posthogAPI.updateTaskRun).toHaveBeenCalledTimes(1);
    });

    it("accumulates every PR a run opens, keeping the first as primary", async () => {
      const s = setup(justNow());
      const second = "https://github.com/PostHog/posthog.com/pull/17765";
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      s.maybeAttachCreatedPr(payload, terminalUpdate(second));
      await flush();
      expect(s.posthogAPI.updateTaskRun).toHaveBeenCalledTimes(2);
      expect(s.posthogAPI.updateTaskRun).toHaveBeenLastCalledWith("t", "r", {
        output: { pr_url: PR_URL, pr_urls: [PR_URL, second] },
      });
      expect(s.detectedPrUrl).toBe(second);
    });

    it("does not let an older PR the run only viewed overwrite the one it created", async () => {
      const viewed = "https://github.com/PostHog/posthog.com/pull/1";
      // The created PR reads as recent; the later, merely-viewed PR reads as old.
      const s = setup(justNow());
      s.fetchPrAttribution = vi.fn(async (url: string) => ({
        createdAt: url === PR_URL ? justNow() : longAgo,
        author: GH_LOGIN,
      }));
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      s.maybeAttachCreatedPr(payload, terminalUpdate(viewed));
      await flush();
      expect(s.detectedPrUrl).toBe(PR_URL);
      expect(s.posthogAPI.updateTaskRun).toHaveBeenCalledTimes(1);
    });

    it("does not attribute a fresh PR authored by someone else (merely viewed)", async () => {
      const s = setup(justNow(), "someone-else");
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      await flush();
      expect(s.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
      expect(s.detectedPrUrl).toBeNull();
    });

    it("attributes a recent PR when the identity is a GitHub App installation (gh api user unavailable)", async () => {
      // Cloud runs authenticate with a GitHub App installation token, for which
      // `gh api user` returns 403 → ghLogin is null. The PR is authored by the
      // app bot (e.g. "app/posthog"); recency alone must carry attribution.
      const s = setup(justNow(), "app/posthog");
      s.fetchGhLogin = vi.fn(async () => null);
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      await flush();
      expect(s.posthogAPI.updateTaskRun).toHaveBeenCalledWith("t", "r", {
        output: { pr_url: PR_URL, pr_urls: [PR_URL] },
      });
      expect(s.detectedPrUrl).toBe(PR_URL);
    });

    it("still rejects an old PR when the identity cannot be resolved (recency guards)", async () => {
      const s = setup(longAgo, "app/posthog");
      s.fetchGhLogin = vi.fn(async () => null);
      s.maybeAttachCreatedPr(payload, terminalUpdate(PR_URL));
      await flush();
      expect(s.posthogAPI.updateTaskRun).not.toHaveBeenCalled();
    });
  });

  describe("buildCloudSystemPrompt", () => {
    it("returns review-first prompt for existing PRs on non-Slack runs", () => {
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt(
        "https://github.com/org/repo/pull/1",
      );
      expect(prompt).toContain("stop with local changes ready for review");
      expect(prompt).toContain("https://github.com/org/repo/pull/1");
      expect(prompt).toContain(
        "Do NOT create new commits, push to the branch, or update the pull request unless the user explicitly asks.",
      );
      expect(prompt).not.toContain("gh pr checkout");
      expect(prompt).not.toContain("Create a draft pull request");
      expect(prompt).toContain("Generated-By: PostHog Code");
      expect(prompt).toContain("Task-Id: test-task-id");
    });

    it("returns default prompt when no prUrl", () => {
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("stop with local changes ready for review");
      expect(prompt).toContain(
        "Do NOT create a branch, commit, push, or open a pull request unless the user explicitly asks.",
      );
      expect(prompt).toContain("Generated-By: PostHog Code");
      expect(prompt).toContain("Task-Id: test-task-id");
      expect(prompt).not.toContain("gh pr create --draft");
      // If the user does explicitly ask for a PR in this review-first mode,
      // the agent must still use the PostHog Code footer, not Claude Code's default.
      expect(prompt).toContain(
        "If the user explicitly asks you to open a pull request",
      );
      expect(prompt).toContain(
        "*Created with [PostHog Code](https://posthog.com/code?ref=pr)*",
      );
      expect(prompt).toContain(".github/pull_request_template.md");
      expect(prompt).toContain("gh issue list --search");
      expect(prompt).toContain("Closes #<n>");
    });

    it("returns default prompt when prUrl is null", () => {
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt(
        null,
      );
      expect(prompt).toContain("stop with local changes ready for review");
    });

    it.each([
      {
        label: "createPr unset",
        config: { repositoryPath: undefined },
        shouldContain: [
          "Cloud Task Execution — No Repository Mode",
          "Clone the repository into /tmp/workspace/repos/<owner>/<repo>",
          "gh repo clone <owner>/<repo> /tmp/workspace/repos/<owner>/<repo>",
          "If the user explicitly asks you to open or update a pull request",
          "open a draft pull request",
          "unless the user explicitly asks",
          ".github/pull_request_template.md",
          "gh issue list --search",
          "Closes #<n>",
          "Generated-By: PostHog Code",
          "Task-Id: test-task-id",
        ],
        shouldNotContain: [],
      },
      {
        label: "createPr false",
        config: { repositoryPath: undefined, createPr: false },
        shouldContain: [
          "Cloud Task Execution — No Repository Mode",
          "You may clone a repository and make local edits in that clone",
          "Do NOT create branches, commits, push changes, or open pull requests in this run",
        ],
        shouldNotContain: ["open a draft pull request", "gh pr create --draft"],
      },
    ])(
      "returns no-repository prompt for $label",
      ({ config, shouldContain, shouldNotContain }) => {
        const s = createServer(config);
        const prompt = (
          s as unknown as TestableServer
        ).buildCloudSystemPrompt();

        for (const text of shouldContain) {
          expect(prompt).toContain(text);
        }
        for (const text of shouldNotContain) {
          expect(prompt).not.toContain(text);
        }
      },
    );

    it("returns auto-PR prompt for Slack-origin runs", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("posthog-code/");
      expect(prompt).toContain("Create a draft pull request");
      expect(prompt).toContain("gh pr create --draft");
      expect(prompt).toContain("Generated-By: PostHog Code");
      expect(prompt).toContain("Task-Id: test-task-id");
      // Slack-origin PRs are attributed to PostHog, not the PostHog Code app.
      expect(prompt).toContain(
        "Created with [PostHog](https://posthog.com?ref=pr)",
      );
      // PR template detection (repo first, org `.github` fallback)
      expect(prompt).toContain(".github/pull_request_template.md");
      expect(prompt).toContain("org's `.github` repo");
      // Related-issue linking
      expect(prompt).toContain("gh issue list --state open --search");
      expect(prompt).toContain("Closes #<n>");
      expect(prompt).toContain("Refs #<n>");
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("returns auto-PR prompt for signal_report-origin runs", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "signal_report";
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("posthog-code/");
      expect(prompt).toContain("Create a draft pull request");
      expect(prompt).toContain("gh pr create --draft");
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("returns auto-PR prompt for manual runs when the user opted into auto-publish", () => {
      const s = createServer({ autoPublish: true });
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("gh pr create --draft");
      expect(prompt).not.toContain("stop with local changes ready for review");
      // Manual runs keep the PostHog Code attribution.
      expect(prompt).toContain(
        "Created with [PostHog Code](https://posthog.com/code?ref=pr)",
      );
    });

    it("keeps review-first prompt when auto-publish is on but createPr is false", () => {
      const s = createServer({ autoPublish: true, createPr: false });
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("stop with local changes ready for review");
      expect(prompt).not.toContain("gh pr create --draft");
    });

    it("auto-publishes in no-repository mode when the user opted in", () => {
      const s = createServer({ repositoryPath: undefined, autoPublish: true });
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("Cloud Task Execution — No Repository Mode");
      expect(prompt).toContain("without waiting to be asked");
      expect(prompt).not.toContain("unless the user explicitly asks for that");
    });

    // Prewarmed runs boot before the user's choice exists; the upgrade is
    // resolved from run state when the first message arrives.
    type WarmTestable = {
      prewarmedRun: boolean;
      session: { payload: { task_id: string; run_id: string } } | null;
      posthogAPI: { getTaskRun: ReturnType<typeof vi.fn> };
      resolveWarmAutoPublishUpgrade(): Promise<string | null>;
      buildCloudSystemPrompt(): string;
    };
    const makeWarmServer = (
      state: Record<string, unknown> | Error,
      overrides: Partial<ConstructorParameters<typeof AgentServer>[0]> = {},
    ): WarmTestable => {
      const t = createServer(overrides) as unknown as WarmTestable;
      t.prewarmedRun = true;
      t.session = {
        payload: { task_id: "test-task-id", run_id: "test-run-id" },
      };
      t.posthogAPI = {
        getTaskRun:
          state instanceof Error
            ? vi.fn(async () => {
                throw state;
              })
            : vi.fn(async () => ({ state })),
      };
      return t;
    };

    it("upgrades a prewarmed run to auto-publish from run state on the first message", async () => {
      const t = makeWarmServer({ prewarmed: true, auto_publish: true });

      const override = await t.resolveWarmAutoPublishUpgrade();
      expect(override).toContain("OVERRIDE PREVIOUS INSTRUCTIONS");
      expect(override).toContain("gh pr create --draft");
      // The flip persists for the rest of the session...
      expect(t.buildCloudSystemPrompt()).toContain("gh pr create --draft");
      // ...and the override is injected only once.
      expect(await t.resolveWarmAutoPublishUpgrade()).toBeNull();
      expect(t.posthogAPI.getTaskRun).toHaveBeenCalledTimes(1);
    });

    it("keeps a prewarmed run review-first when run state has no auto_publish", async () => {
      const t = makeWarmServer({ prewarmed: true });

      expect(await t.resolveWarmAutoPublishUpgrade()).toBeNull();
      expect(t.buildCloudSystemPrompt()).toContain(
        "stop with local changes ready for review",
      );
      expect(await t.resolveWarmAutoPublishUpgrade()).toBeNull();
      expect(t.posthogAPI.getTaskRun).toHaveBeenCalledTimes(1);
    });

    it("never upgrades a prewarmed run when createPr is false", async () => {
      // PostHog AI warm runs launch with createPr=false; auto-publish must not
      // override that even if auto_publish somehow lands in state.
      const t = makeWarmServer(
        { prewarmed: true, auto_publish: true },
        { createPr: false },
      );

      expect(await t.resolveWarmAutoPublishUpgrade()).toBeNull();
      expect(t.posthogAPI.getTaskRun).not.toHaveBeenCalled();
      expect(t.buildCloudSystemPrompt()).toContain(
        "stop with local changes ready for review",
      );
    });

    it("retries the state fetch on a later message when it fails", async () => {
      const t = makeWarmServer(new Error("fetch failed"));
      expect(await t.resolveWarmAutoPublishUpgrade()).toBeNull();

      t.posthogAPI.getTaskRun = vi.fn(async () => ({
        state: { prewarmed: true, auto_publish: true },
      }));
      expect(await t.resolveWarmAutoPublishUpgrade()).toContain(
        "gh pr create --draft",
      );
    });

    it.each([
      { label: "Slack", origin: "slack" },
      { label: "signal_report", origin: "signal_report" },
    ])(
      "guards the auto-PR prompt against duplicating an existing PR on $label-origin runs",
      ({ origin }) => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = origin;
        const s = createServer();
        const prompt = (
          s as unknown as TestableServer
        ).buildCloudSystemPrompt();
        // Still the new-PR branch...
        expect(prompt).toContain("gh pr create --draft");
        // ...but tells the agent to continue an existing linked PR instead of duplicating.
        expect(prompt).toContain("implementation_pr_url");
        expect(prompt).toContain("gh pr checkout <url>");
        expect(prompt).toMatch(/do not open a second PR/i);
        delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
      },
    );

    it("returns PR-update prompt for existing PRs on Slack-origin runs", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt(
        "https://github.com/org/repo/pull/1",
      );
      expect(prompt).toContain(
        "If it is not already checked out, check it out with `gh pr checkout https://github.com/org/repo/pull/1`",
      );
      expect(prompt).toContain(
        "Do not check it out again when it is already active",
      );
      expect(prompt).not.toContain("Check out the existing PR branch");
      expect(prompt).toContain("git_signed_commit");
      expect(prompt).toContain("Committing (signed commits required)");
      expect(prompt).not.toContain("Create a draft pull request");
      // Review-comment thread handling: reply + resolve
      expect(prompt).toContain("review thread");
      expect(prompt).toContain("/pulls/{n}/comments/{id}/replies");
      expect(prompt).toContain("resolveReviewThread");
      expect(prompt).toContain(
        "Do NOT push fixes for review comments without replying to and resolving each related thread.",
      );
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("includes --base flag when baseBranch is configured", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      server = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
        baseBranch: "add-yolo-to-readme",
      });
      const prompt = (
        server as unknown as TestableServer
      ).buildCloudSystemPrompt();
      expect(prompt).toContain(
        "gh pr create --draft --base add-yolo-to-readme",
      );
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("omits --base flag when baseBranch is not configured", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer();
      const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt();
      expect(prompt).toContain("gh pr create --draft`");
      expect(prompt).not.toContain("--base");
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("disables auto-publish for Slack-origin runs when createPr is false", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      server = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
        createPr: false,
      });
      const prompt = (
        server as unknown as TestableServer
      ).buildCloudSystemPrompt();
      expect(prompt).toContain("stop with local changes ready for review");
      expect(prompt).not.toContain("gh pr create --draft");
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("disables auto-publish for existing PRs when createPr is false", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      server = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
        createPr: false,
      });
      const prompt = (
        server as unknown as TestableServer
      ).buildCloudSystemPrompt("https://github.com/org/repo/pull/1");
      expect(prompt).toContain("stop with local changes ready for review");
      expect(prompt).not.toContain("gh pr checkout");
      expect(prompt).not.toContain("Push to the existing PR branch");
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    describe("identity instructions", () => {
      it.each([
        {
          label: "no repository, no PR",
          config: { repositoryPath: undefined },
        },
        { label: "repository, no PR", config: {} },
      ])(
        "injects PostHog Slack app identity for Slack-origin runs ($label)",
        ({ config }) => {
          process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
          const s = createServer(config);
          const prompt = (
            s as unknown as TestableServer
          ).buildCloudSystemPrompt();
          expect(prompt).toContain("# Identity");
          expect(prompt).toContain("PostHog Slack app");
          expect(prompt).toContain("Do NOT refer to yourself as Claude");
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        },
      );

      it.each([
        {
          label: "no repository, no PR",
          config: { repositoryPath: undefined },
        },
        { label: "repository, no PR", config: {} },
      ])(
        "injects concise response-style guidance for Slack-origin runs ($label)",
        ({ config }) => {
          process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
          const s = createServer(config);
          const prompt = (
            s as unknown as TestableServer
          ).buildCloudSystemPrompt();
          expect(prompt).toContain("# Response Style");
          expect(prompt).toContain("be concise by default");
          expect(prompt).toContain(
            "Answer simple questions in a single sentence",
          );
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        },
      );

      it.each([
        { label: "no origin set", origin: undefined },
        { label: "signal_report origin", origin: "signal_report" },
        { label: "posthog_code origin", origin: "posthog_code" },
      ])(
        "omits response-style guidance for non-Slack runs ($label)",
        ({ origin }) => {
          if (origin) {
            process.env.POSTHOG_CODE_INTERACTION_ORIGIN = origin;
          } else {
            delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
          }
          const s = createServer();
          const prompt = (
            s as unknown as TestableServer
          ).buildCloudSystemPrompt();
          expect(prompt).not.toContain("# Response Style");
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        },
      );

      it("injects identity for Slack-origin runs with an existing PR", () => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
        const s = createServer();
        const prompt = (s as unknown as TestableServer).buildCloudSystemPrompt(
          "https://github.com/org/repo/pull/1",
        );
        expect(prompt).toContain("# Identity");
        expect(prompt).toContain("PostHog Slack app");
        delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
      });

      it.each([
        { label: "no origin set", origin: undefined },
        { label: "signal_report origin", origin: "signal_report" },
        { label: "posthog_code origin", origin: "posthog_code" },
      ])("omits identity block for non-Slack runs ($label)", ({ origin }) => {
        if (origin) {
          process.env.POSTHOG_CODE_INTERACTION_ORIGIN = origin;
        } else {
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        }
        const s = createServer();
        const prompt = (
          s as unknown as TestableServer
        ).buildCloudSystemPrompt();
        expect(prompt).not.toContain("# Identity");
        expect(prompt).not.toContain("PostHog Slack app");
        delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
      });
    });

    describe("PR body guidance (why context + brevity + footer)", () => {
      it("instructs Why, brevity, and the plain footer (no Slack link) when auto-creating a Slack PR without a thread URL", () => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
        try {
          const prompt = (
            createServer() as unknown as TestableServer
          ).buildCloudSystemPrompt();
          expect(prompt).toContain("gh pr create --draft");
          // why context
          expect(prompt).toContain("**Why**");
          expect(prompt).toContain("the reason the user asked for this change");
          // brevity
          expect(prompt).toContain("Keep the PR description brief");
          expect(prompt).toContain("do NOT enumerate every change");
          // plain footer, no Slack link; Slack-origin PRs are branded "PostHog"
          expect(prompt).toContain(
            "*Created with [PostHog](https://posthog.com?ref=pr)*",
          );
          expect(prompt).not.toContain("from a [Slack thread]");
          expect(prompt).not.toContain("PostHog Code](https://posthog.com");
        } finally {
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        }
      });

      it("embeds the Slack thread link in the footer when one is available", () => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
        try {
          const prompt = (
            createServer() as unknown as TestableServer
          ).buildCloudSystemPrompt(
            null,
            "https://posthog.slack.com/archives/C123/p456",
          );
          expect(prompt).toContain(
            "*Created with [PostHog](https://posthog.com?ref=pr) from a [Slack thread](https://posthog.slack.com/archives/C123/p456)*",
          );
          // The Why bullet no longer carries the thread link.
          expect(prompt).not.toContain(
            "this task started from a Slack thread, also link it",
          );
        } finally {
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        }
      });

      it("embeds the inbox report link in the footer for a signal_report run", () => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "signal_report";
        try {
          const prompt = (
            createServer() as unknown as TestableServer
          ).buildCloudSystemPrompt(
            null,
            null,
            "http://localhost:8000/project/1/inbox/rep_1",
          );
          expect(prompt).toContain(
            "*Created with [PostHog](https://posthog.com?ref=pr) from an [inbox report](http://localhost:8000/project/1/inbox/rep_1)*",
          );
          expect(prompt).not.toContain("from a [Slack thread]");
        } finally {
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        }
      });

      it("prefers the Slack thread link over the inbox report link when both are present", () => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
        try {
          const prompt = (
            createServer() as unknown as TestableServer
          ).buildCloudSystemPrompt(
            null,
            "https://posthog.slack.com/archives/C123/p456",
            "http://localhost:8000/project/1/inbox/rep_1",
          );
          expect(prompt).toContain("from a [Slack thread]");
          expect(prompt).not.toContain("from an [inbox report]");
        } finally {
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        }
      });

      it("instructs Why, brevity, and the plain footer on the non-Slack no-repository path", () => {
        delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        const prompt = (
          createServer({
            repositoryPath: undefined,
          }) as unknown as TestableServer
        ).buildCloudSystemPrompt();
        expect(prompt).toContain("open a draft pull request");
        expect(prompt).toContain("**Why**");
        expect(prompt).toContain("Keep the PR description brief");
        expect(prompt).toContain(
          "*Created with [PostHog Code](https://posthog.com/code?ref=pr)*",
        );
        expect(prompt).not.toContain("from a [Slack thread]");
      });

      it("embeds the Slack thread link in the footer on the no-repository path when one is available", () => {
        process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
        try {
          const prompt = (
            createServer({
              repositoryPath: undefined,
            }) as unknown as TestableServer
          ).buildCloudSystemPrompt(
            null,
            "https://posthog.slack.com/archives/C123/p456",
          );
          expect(prompt).toContain(
            "*Created with [PostHog](https://posthog.com?ref=pr) from a [Slack thread](https://posthog.slack.com/archives/C123/p456)*",
          );
        } finally {
          delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
        }
      });
    });
  });

  describe("buildDetectedPrContext", () => {
    const prUrl = "https://github.com/org/repo/pull/1";

    it("returns review-first PR context for non-Slack runs", () => {
      const s = createServer();
      const context = (s as unknown as TestableServer).buildDetectedPrContext(
        prUrl,
      );
      expect(context).toContain("stop with local changes ready for review");
      expect(context).toContain(
        "Do NOT create commits, push to the PR branch, update the pull request",
      );
      expect(context).not.toContain("gh pr checkout");
    });

    it("avoids redundant PR checkout for auto-update runs", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer();
      const context = (s as unknown as TestableServer).buildDetectedPrContext(
        prUrl,
      );
      expect(context).toContain(
        `If it is not already checked out, check it out with \`gh pr checkout ${prUrl}\``,
      );
      expect(context).toContain(
        "Do not check it out again when it is already active",
      );
      expect(context).toContain(
        "Make changes, commit, and push to that branch",
      );
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    it("returns review-first PR context when createPr is false", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      server = new AgentServer({
        port,
        jwtPublicKey: TEST_PUBLIC_KEY,
        repositoryPath: repo.path,
        apiUrl: "http://localhost:8000",
        apiKey: "test-api-key",
        projectId: 1,
        mode: "interactive",
        taskId: "test-task-id",
        runId: "test-run-id",
        createPr: false,
      });
      const context = (
        server as unknown as TestableServer
      ).buildDetectedPrContext(prUrl);
      expect(context).toContain("stop with local changes ready for review");
      expect(context).not.toContain("gh pr checkout");
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });
  });

  describe("buildExistingPrCheckoutPromise", () => {
    const prUrl = "https://github.com/org/repo/pull/1";

    afterEach(() => {
      delete process.env.POSTHOG_CODE_INTERACTION_ORIGIN;
    });

    // Guards the gating condition: a review-first run (no auto-publish) must
    // not silently check out a PR branch the prompt told the agent to leave
    // alone. Regressing the guard to always-checkout would fail here.
    it("does not check out when auto-publish is off", () => {
      const s = createServer();
      const promise = (
        s as unknown as TestableServer
      ).buildExistingPrCheckoutPromise(prUrl);
      expect(promise).toBeNull();
    });

    it("does not check out when there is no prUrl", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer();
      const promise = (
        s as unknown as TestableServer
      ).buildExistingPrCheckoutPromise(null);
      expect(promise).toBeNull();
    });

    it("does not check out when createPr is false, even on a Slack-origin run", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer({ createPr: false });
      const promise = (
        s as unknown as TestableServer
      ).buildExistingPrCheckoutPromise(prUrl);
      expect(promise).toBeNull();
    });

    it("does not check out when no repository is connected", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer({ repositoryPath: undefined });
      const promise = (
        s as unknown as TestableServer
      ).buildExistingPrCheckoutPromise(prUrl);
      expect(promise).toBeNull();
    });

    it("starts a checkout when auto-publish is on for a Slack-origin run", () => {
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN = "slack";
      const s = createServer();
      const promise = (
        s as unknown as TestableServer
      ).buildExistingPrCheckoutPromise(prUrl);
      expect(promise).toBeInstanceOf(Promise);
      // Sanity: the promise resolves to a checkout result shape (it will fail
      // against the synthetic URL with no real gh, which is fine — we only
      // assert the promise was actually kicked off).
      expect(typeof promise).toBe("object");
    });

    // Guards the failure fallback: a transient gh failure must surface as a
    // warn, never throw or abort startup. Regressing the failed branch to
    // `throw` would fail here.
    it("logs a warning for a failed checkout result without throwing", () => {
      const s = createServer();
      expect(() =>
        (s as unknown as TestableServer).logExistingPrCheckoutResult(prUrl, {
          status: "failed",
          error: "gh unavailable",
        }),
      ).not.toThrow();
    });
  });
});

// Exercises getPendingUserPrompt directly (no HTTP server / git repo) so we can
// assert how the initial cloud prompt degrades when an attached file can't be
// hydrated — the case behind a pasted-text task reaching the agent as a bare
// "Attached files: …" description with no readable file.
describe("AgentServer pending user attachments", () => {
  interface PendingPromptInternals {
    posthogAPI: {
      getTaskRun: (taskId: string, runId: string) => Promise<TaskRun>;
      downloadArtifact: (
        taskId: string,
        runId: string,
        storagePath: string,
      ) => Promise<ArrayBuffer | null>;
    };
    getPendingUserPrompt(
      taskRun: TaskRun | null,
    ): Promise<{ prompt: ContentBlock[] } | null>;
  }

  let tempDir: string;
  let server: AgentServer | undefined;

  beforeEach(async () => {
    tempDir = await mkdtemp(join(tmpdir(), "agent-pending-"));
  });

  afterEach(async () => {
    vi.useRealTimers();
    await server?.stop();
    server = undefined;
    await rm(tempDir, { recursive: true, force: true });
  });

  const buildInternals = (): PendingPromptInternals => {
    server = new AgentServer({
      port: getNextTestPort(),
      jwtPublicKey: TEST_PUBLIC_KEY,
      repositoryPath: tempDir,
      apiUrl: "http://localhost:8000",
      apiKey: "test-api-key",
      projectId: 1,
      mode: "interactive",
      taskId: "test-task-id",
      runId: "test-run-id",
    });
    return server as unknown as PendingPromptInternals;
  };

  it("appends an explicit notice when a pending attachment never reaches the manifest", async () => {
    vi.useFakeTimers();
    const internals = buildInternals();
    // Refetch still can't see the attachment (truly absent, not just lagging).
    const getTaskRun = vi.fn(async () =>
      createTaskRun({
        state: { pending_user_artifact_ids: ["missing-attachment"] },
        artifacts: [],
      }),
    );
    internals.posthogAPI.getTaskRun = getTaskRun;

    const resultPromise = internals.getPendingUserPrompt(
      createTaskRun({
        state: { pending_user_artifact_ids: ["missing-attachment"] },
        artifacts: [],
      }),
    );
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    // Retried to recover a lagging manifest, then surfaced an explicit notice
    // instead of falling back to the misleading attachment summary.
    expect(getTaskRun).toHaveBeenCalledTimes(4);
    expect(result).not.toBeNull();
    expect(result?.prompt).toHaveLength(1);
    const [block] = result?.prompt ?? [];
    expect(block?.type).toBe("text");
    expect((block as { text: string }).text).toContain("could not be loaded");
  });

  it("recovers a pending attachment from a refetched run manifest", async () => {
    const internals = buildInternals();
    internals.posthogAPI.getTaskRun = vi.fn(async () =>
      createTaskRun({
        state: { pending_user_artifact_ids: ["att-1"] },
        artifacts: [
          {
            id: "att-1",
            name: "pasted-text.txt",
            type: "user_attachment",
            storage_path: "tasks/artifacts/pasted-text.txt",
            content_type: "text/plain",
          },
        ],
      }),
    );
    const downloadArtifact = vi.fn(async () =>
      exactArrayBuffer(new TextEncoder().encode("pasted body")),
    );
    internals.posthogAPI.downloadArtifact = downloadArtifact;

    const result = await internals.getPendingUserPrompt(
      createTaskRun({
        state: { pending_user_artifact_ids: ["att-1"] },
        artifacts: [],
      }),
    );

    expect(downloadArtifact).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "tasks/artifacts/pasted-text.txt",
    );
    const resourceLinks = result?.prompt.filter(
      (block) => block.type === "resource_link",
    );
    expect(resourceLinks).toHaveLength(1);
    // No "couldn't load" notice once the attachment is recovered.
    const hasNotice = result?.prompt.some(
      (block) =>
        block.type === "text" &&
        (block as { text: string }).text.includes("could not be loaded"),
    );
    expect(hasNotice).toBe(false);
  });

  it("recovers a pending attachment that only lands in a later manifest refetch", async () => {
    vi.useFakeTimers();
    const internals = buildInternals();
    internals.posthogAPI.getTaskRun = vi
      .fn()
      .mockResolvedValueOnce(
        createTaskRun({
          state: { pending_user_artifact_ids: ["att-1"] },
          artifacts: [],
        }),
      )
      .mockResolvedValueOnce(
        createTaskRun({
          state: { pending_user_artifact_ids: ["att-1"] },
          artifacts: [],
        }),
      )
      .mockResolvedValue(
        createTaskRun({
          state: { pending_user_artifact_ids: ["att-1"] },
          artifacts: [
            {
              id: "att-1",
              name: "pasted-text.txt",
              type: "user_attachment",
              storage_path: "tasks/artifacts/pasted-text.txt",
              content_type: "text/plain",
            },
          ],
        }),
      );
    internals.posthogAPI.downloadArtifact = vi.fn(async () =>
      exactArrayBuffer(new TextEncoder().encode("pasted body")),
    );

    const resultPromise = internals.getPendingUserPrompt(
      createTaskRun({
        state: { pending_user_artifact_ids: ["att-1"] },
        artifacts: [],
      }),
    );
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(internals.posthogAPI.getTaskRun).toHaveBeenCalledTimes(3);
    expect(result?.prompt.some((block) => block.type === "resource_link")).toBe(
      true,
    );
    expect(
      result?.prompt.some(
        (block) =>
          block.type === "text" && block.text.includes("could not be loaded"),
      ),
    ).toBe(false);
  });

  it("preserves an initially visible attachment while polling for another", async () => {
    vi.useFakeTimers();
    const internals = buildInternals();
    const firstArtifact = {
      id: "att-1",
      name: "first.txt",
      type: "user_attachment" as const,
      storage_path: "tasks/artifacts/first.txt",
      content_type: "text/plain",
    };
    const secondArtifact = {
      id: "att-2",
      name: "second.txt",
      type: "user_attachment" as const,
      storage_path: "tasks/artifacts/second.txt",
      content_type: "text/plain",
    };
    internals.posthogAPI.getTaskRun = vi
      .fn()
      .mockResolvedValueOnce(
        createTaskRun({
          state: { pending_user_artifact_ids: ["att-1", "att-2"] },
          artifacts: [],
        }),
      )
      .mockResolvedValue(
        createTaskRun({
          state: { pending_user_artifact_ids: ["att-1", "att-2"] },
          artifacts: [secondArtifact],
        }),
      );
    internals.posthogAPI.downloadArtifact = vi.fn(async () =>
      exactArrayBuffer(new TextEncoder().encode("body")),
    );

    const resultPromise = internals.getPendingUserPrompt(
      createTaskRun({
        state: { pending_user_artifact_ids: ["att-1", "att-2"] },
        artifacts: [firstArtifact],
      }),
    );
    await vi.runAllTimersAsync();
    const result = await resultPromise;

    expect(
      result?.prompt.filter((block) => block.type === "resource_link"),
    ).toHaveLength(2);
    expect(
      result?.prompt.some(
        (block) =>
          block.type === "text" && block.text.includes("could not be loaded"),
      ),
    ).toBe(false);
  });

  it("returns null without refetching when no pending artifacts were declared", async () => {
    const internals = buildInternals();
    const getTaskRun = vi.fn();
    internals.posthogAPI.getTaskRun = getTaskRun;

    const result = await internals.getPendingUserPrompt(
      createTaskRun({ state: {}, artifacts: [] }),
    );

    expect(result).toBeNull();
    expect(getTaskRun).not.toHaveBeenCalled();
  });

  it("warns once (not twice) about a missing artifact across the speculative and post-refetch resolves", async () => {
    vi.useFakeTimers();
    const internals = buildInternals();
    // A non-empty manifest that never lists the requested id — so getArtifactsById
    // reaches its per-id "missing" warning on both the pre- and post-refetch calls
    // (an empty manifest would short-circuit before warning at all).
    const decoyManifest = [
      {
        id: "unrelated-artifact",
        name: "other.txt",
        type: "user_attachment" as const,
      },
    ];
    internals.posthogAPI.getTaskRun = vi.fn(async () =>
      createTaskRun({
        state: { pending_user_artifact_ids: ["missing-attachment"] },
        artifacts: decoyManifest,
      }),
    );
    const loggerHost = internals as unknown as {
      logger: { warn: (...args: unknown[]) => void };
    };
    const warnSpy = vi
      .spyOn(loggerHost.logger, "warn")
      .mockImplementation(() => {});

    const resultPromise = internals.getPendingUserPrompt(
      createTaskRun({
        state: { pending_user_artifact_ids: ["missing-attachment"] },
        artifacts: decoyManifest,
      }),
    );
    await vi.runAllTimersAsync();
    await resultPromise;

    // The speculative pre-refetch resolve stays quiet (a miss there is expected);
    // only the post-refetch resolve emits the per-id "missing" warning.
    const manifestWarnings = warnSpy.mock.calls.filter(
      ([message]) => message === "Pending artifact missing from run manifest",
    );
    expect(manifestWarnings).toHaveLength(1);
  });
});
