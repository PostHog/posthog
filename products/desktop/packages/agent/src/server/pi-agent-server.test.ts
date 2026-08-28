import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { PiAgentServer } from "./pi-agent-server";
import type { AgentServerConfig } from "./types";

function config(overrides: Partial<AgentServerConfig> = {}): AgentServerConfig {
  return {
    port: 0,
    jwtPublicKey: "public-key",
    apiUrl: "https://us.posthog.com",
    apiKey: "token",
    projectId: 1,
    mode: "interactive",
    taskId: "task-1",
    runId: "run-1",
    sandboxId: "sandbox-1",
    taskRunSessionToken: "task-run-token",
    ...overrides,
  };
}

describe("PiAgentServer", () => {
  it("logs session initialization diagnostics when setup fails", async () => {
    const payload = { task_id: "task-1", run_id: "run-1" };
    const server = new PiAgentServer(
      config({ model: "anthropic/claude-opus-5" }),
    ) as unknown as {
      logger: { error: ReturnType<typeof vi.fn> };
      createSession(sessionPayload: typeof payload): Promise<void>;
      initializeSession(
        sessionPayload: typeof payload,
        sseController: null,
      ): Promise<void>;
      createRunTelemetry: ReturnType<typeof vi.fn>;
    };
    const append = vi.fn();
    const shutdown = vi.fn(async () => {});
    server.createRunTelemetry = vi.fn(() => ({ append, shutdown }));
    server.createSession = vi.fn(async () => {
      throw new Error("Pi RPC startup failed");
    });
    const errorSpy = vi.spyOn(server.logger, "error");

    await expect(server.initializeSession(payload, null)).rejects.toThrow(
      "Pi RPC startup failed",
    );

    expect(errorSpy).toHaveBeenCalledWith(
      "Pi session initialization failed",
      expect.objectContaining({
        runtimeAdapter: "pi",
        initializationPhase: "session_setup",
        initMs: expect.any(Number),
        requestedModel: "anthropic/claude-opus-5",
        gatewayConfigured: true,
        taskId: "task-1",
        taskRunId: "run-1",
        errorDetail: expect.objectContaining({
          message: "Pi RPC startup failed",
        }),
      }),
    );
    expect(append).toHaveBeenCalledWith(
      "run-1",
      expect.objectContaining({
        notification: expect.objectContaining({
          method: "_posthog/initialization_failed",
          params: expect.objectContaining({
            runtimeAdapter: "pi",
            initializationPhase: "session_setup",
            errorType: "error",
          }),
        }),
      }),
    );
    expect(shutdown).toHaveBeenCalledOnce();
  });

  it.each([
    ["task", { task_id: "task-2", run_id: "run-1", team_id: 1 }],
    ["run", { task_id: "task-1", run_id: "run-2", team_id: 1 }],
    ["team", { task_id: "task-1", run_id: "run-1", team_id: 2 }],
  ])("rejects a token for a different %s", (_field, identity) => {
    const server = new PiAgentServer(config()) as unknown as {
      assertConfiguredRun(payload: Record<string, unknown>): void;
    };

    expect(() =>
      server.assertConfiguredRun({
        ...identity,
        user_id: 1,
        distinct_id: "user-1",
        mode: "interactive",
      }),
    ).toThrow("Token does not match the configured task run");
  });

  it("persists translated Pi events at the turn boundary", async () => {
    const appendTaskRunLog = vi.fn(async () => ({}));
    const server = new PiAgentServer(config()) as unknown as {
      posthogAPI: { appendTaskRunLog: typeof appendTaskRunLog };
      handleEvent(event: Record<string, unknown>): void;
      logFlushQueue: Promise<void>;
    };
    server.posthogAPI.appendTaskRunLog = appendTaskRunLog;

    server.handleEvent({
      type: "user_message",
      timestamp: 1,
      content: [{ type: "text", text: "hello" }],
    });
    server.handleEvent({
      type: "turn_completed",
      timestamp: 2,
      totalTokens: 1_234,
    });
    await server.logFlushQueue;

    expect(appendTaskRunLog).toHaveBeenCalledWith("task-1", "run-1", [
      {
        id: expect.any(String),
        type: "pi_event",
        timestamp: expect.any(String),
        event: {
          type: "user_message",
          timestamp: 1,
          content: [{ type: "text", text: "hello" }],
          sourceId: expect.any(String),
        },
      },
      {
        id: expect.any(String),
        type: "pi_event",
        timestamp: expect.any(String),
        event: {
          type: "turn_completed",
          timestamp: 2,
          totalTokens: 1_234,
          sourceId: expect.any(String),
        },
      },
    ]);
  });

  it("relays MCP permission requests and persists always-allow responses", async () => {
    const approveMcpTool = vi.fn(async () => {});
    const respondMcpToolPermission = vi.fn();
    const server = new PiAgentServer(config()) as unknown as {
      posthogAPI: { approveMcpTool: typeof approveMcpTool };
      session: unknown;
      pendingEvents: Record<string, unknown>[];
      handleMcpToolPermissionRequest(request: Record<string, unknown>): void;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.posthogAPI.approveMcpTool = approveMcpTool;
    server.session = {
      runtime: { client: { respondMcpToolPermission } },
    };
    const request = {
      requestId: "request-1",
      serverName: "Cloudflare",
      toolName: "search",
      installationId: "installation-1",
      arguments: { query: "workers" },
      description: "Search resources",
    };

    server.handleMcpToolPermissionRequest(request);

    expect(server.pendingEvents).toContainEqual(
      expect.objectContaining({
        type: "permission_request",
        requestId: "request-1",
        toolCall: expect.objectContaining({
          rawInput: { query: "workers" },
        }),
        options: [
          expect.objectContaining({ optionId: "allow_always" }),
          expect.objectContaining({ optionId: "reject" }),
        ],
      }),
    );

    await server.executeCommand("pi/rpc", {
      command: {
        id: "response-1",
        type: "mcp_permission_response",
        requestId: "request-1",
        decision: "allow_always",
      },
    });

    expect(approveMcpTool).toHaveBeenCalledWith("installation-1", "search");
    expect(respondMcpToolPermission).toHaveBeenCalledWith(
      "request-1",
      "allow_always",
    );
  });

  it("bounds events retained while no SSE client is connected", () => {
    const server = new PiAgentServer(config()) as unknown as {
      broadcast(event: Record<string, unknown>): void;
      pendingEvents: Record<string, unknown>[];
    };

    for (let index = 0; index < 1_100; index++) {
      server.broadcast({ type: "test", index });
    }

    expect(server.pendingEvents).toHaveLength(1_000);
    expect(server.pendingEvents[0]).toEqual({ type: "test", index: 100 });
  });

  it("coalesces replay and log buffers for repeated tool updates", () => {
    const server = new PiAgentServer(config()) as unknown as {
      broadcast(event: Record<string, unknown>): void;
      pendingEvents: Record<string, unknown>[];
      pendingLogEntries: Array<{ event?: Record<string, unknown> }>;
    };

    server.broadcast({
      type: "pi_event",
      event: {
        type: "tool_call_updated",
        timestamp: 1,
        toolCall: { id: "tool-1", content: [{ type: "content" }] },
      },
    });
    server.broadcast({
      type: "pi_event",
      event: {
        type: "tool_call_updated",
        timestamp: 2,
        toolCall: { id: "tool-1", status: "completed" },
      },
    });

    expect(server.pendingEvents).toHaveLength(1);
    expect(server.pendingLogEntries).toHaveLength(1);
    expect(server.pendingLogEntries[0]?.event).toMatchObject({
      timestamp: 2,
      toolCall: {
        id: "tool-1",
        status: "completed",
        content: [{ type: "content" }],
      },
    });
  });

  it("flushes long-running conversation logs in bounded batches", async () => {
    const appendTaskRunLog = vi.fn(
      async (_taskId: string, _runId: string, _entries: unknown[]) => ({}),
    );
    const server = new PiAgentServer(config()) as unknown as {
      posthogAPI: { appendTaskRunLog: typeof appendTaskRunLog };
      handleEvent(event: Record<string, unknown>): void;
      logFlushQueue: Promise<void>;
    };
    server.posthogAPI.appendTaskRunLog = appendTaskRunLog;

    for (let index = 0; index < 100; index++) {
      server.handleEvent({
        type: "assistant_message_chunk",
        timestamp: index,
        content: { type: "text", text: String(index) },
      });
    }
    await server.logFlushQueue;

    expect(appendTaskRunLog).toHaveBeenCalledOnce();
    expect(appendTaskRunLog.mock.calls[0]?.[2]).toHaveLength(100);
  });

  it("uses the durable message id for an idle native Pi prompt", async () => {
    const sendCommand = vi.fn(
      async (_command: Record<string, unknown>) => ({}),
    );
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: {
          getState: vi.fn(async () => ({ isStreaming: false })),
        },
        sendCommand,
      },
    };

    await server.executeCommand("user_message", {
      content: "hello",
      messageId: "message-1",
    });

    expect(sendCommand).toHaveBeenCalledWith({
      id: "message-1",
      type: "prompt",
      message: "hello",
      images: [],
    });
  });

  it("preserves the native Pi user prompt when auto-publish is enabled", async () => {
    const sendCommand = vi.fn(
      async (_command: Record<string, unknown>) => ({}),
    );
    const server = new PiAgentServer(
      config({ autoPublish: true, createPr: true }),
    ) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: { getState: vi.fn(async () => ({ isStreaming: false })) },
        sendCommand,
      },
    };

    await server.executeCommand("user_message", { content: "fix it" });

    expect(sendCommand.mock.calls[0]?.[0].message).toBe("fix it");
  });

  it("hydrates cloud artifacts into native Pi prompt inputs", async () => {
    const repositoryPath = await mkdtemp(join(tmpdir(), "pi-attachments-"));
    const sendCommand = vi.fn(
      async (_command: Record<string, unknown>) => ({}),
    );
    const downloadArtifact = vi
      .fn()
      .mockResolvedValueOnce(Buffer.from("notes"))
      .mockResolvedValueOnce(Buffer.from("image"));
    const server = new PiAgentServer(config({ repositoryPath })) as unknown as {
      posthogAPI: { downloadArtifact: typeof downloadArtifact };
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.posthogAPI.downloadArtifact = downloadArtifact;
    server.session = {
      runtime: {
        client: {
          getState: vi.fn(async () => ({ isStreaming: false })),
        },
        sendCommand,
      },
    };

    await server.executeCommand("user_message", {
      content: "Read these",
      artifacts: [
        {
          id: "file-1",
          name: "notes.txt",
          type: "user_attachment",
          content_type: "text/plain",
          storage_path: "artifacts/notes.txt",
        },
        {
          id: "image-1",
          name: "image.png",
          type: "user_attachment",
          content_type: "image/png",
          storage_path: "artifacts/image.png",
        },
      ],
    });

    const command = sendCommand.mock.calls[0][0];
    const filePath = join(
      repositoryPath,
      ".posthog",
      "attachments",
      "file-1-notes.txt",
    );
    expect(command.message).toContain(filePath);
    await expect(readFile(filePath, "utf8")).resolves.toBe("notes");
    expect(command.images).toEqual([
      {
        type: "image",
        data: Buffer.from("image").toString("base64"),
        mimeType: "image/png",
        fileName: "image.png",
      },
    ]);

    await rm(repositoryPath, { recursive: true });
  });

  it("aborts the streaming run and re-prompts when a steer arrives", async () => {
    const sendCommand = vi.fn(async (_command: Record<string, unknown>) => ({
      success: true,
    }));
    const order: string[] = [];
    const abort = vi.fn(async () => {
      order.push("abort");
    });
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: {
          getState: vi.fn(async () => ({ isStreaming: true })),
          abort,
        },
        sendCommand: vi.fn(async (command: Record<string, unknown>) => {
          order.push("sendCommand");
          return sendCommand(command);
        }),
      },
    };

    await server.executeCommand("user_message", {
      content: "stop, do this instead",
      messageId: "message-1",
      steer: true,
    });

    expect(order).toEqual(["abort", "sendCommand"]);
    expect(sendCommand).toHaveBeenCalledTimes(1);
    expect(sendCommand).toHaveBeenCalledWith({
      id: "message-1",
      type: "prompt",
      message: "stop, do this instead",
      images: [],
    });
  });

  it("queues a steer that pi rejects because another run took the idle slot", async () => {
    const sendCommand = vi.fn(async (command: Record<string, unknown>) => {
      if (command.type === "prompt") {
        return { success: false, error: "Agent is already processing." };
      }
      return { success: true };
    });
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: {
          getState: vi.fn(async () => ({ isStreaming: true })),
          abort: vi.fn(async () => {}),
        },
        sendCommand,
      },
    };

    const result = await server.executeCommand("user_message", {
      content: "stop, do this instead",
      messageId: "message-3",
      steer: true,
    });

    expect(sendCommand).toHaveBeenLastCalledWith({
      id: "message-3",
      type: "follow_up",
      message: "stop, do this instead",
      images: [],
    });
    expect(result).toMatchObject({ success: true });
  });

  it("declines a steer whose re-prompt fails while pi stays idle so the host redelivers", async () => {
    const sendCommand = vi.fn(async (command: Record<string, unknown>) => {
      if (command.type === "prompt") {
        return {
          success: false,
          error: "Cannot submit a prompt while compaction is in progress.",
        };
      }
      return { success: true };
    });
    const getState = vi
      .fn()
      .mockResolvedValueOnce({ isStreaming: true })
      .mockResolvedValueOnce({ isStreaming: false });
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: {
          getState,
          abort: vi.fn(async () => {}),
        },
        sendCommand,
      },
    };

    const result = await server.executeCommand("user_message", {
      content: "stop, do this instead",
      messageId: "message-4",
      steer: true,
    });

    expect(sendCommand).toHaveBeenCalledTimes(1);
    expect(sendCommand).toHaveBeenCalledWith({
      id: "message-4",
      type: "prompt",
      message: "stop, do this instead",
      images: [],
    });
    expect(result).toMatchObject({ success: false });
  });

  it("queues a mid-turn message that is not a steer instead of aborting", async () => {
    const sendCommand = vi.fn(
      async (_command: Record<string, unknown>) => ({}),
    );
    const abort = vi.fn(async () => {});
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: {
          getState: vi.fn(async () => ({ isStreaming: true })),
          abort,
        },
        sendCommand,
      },
    };

    await server.executeCommand("user_message", {
      content: "when you are done, also update the docs",
      messageId: "message-2",
    });

    expect(abort).not.toHaveBeenCalled();
    expect(sendCommand).toHaveBeenCalledWith({
      id: "message-2",
      type: "follow_up",
      message: "when you are done, also update the docs",
      images: [],
    });
  });

  it("allows a failed user-message delivery to be retried", async () => {
    const sendCommand = vi
      .fn()
      .mockRejectedValueOnce(new Error("delivery failed"))
      .mockResolvedValueOnce(undefined);
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = {
      runtime: {
        client: {
          getState: vi.fn(async () => ({ isStreaming: false })),
        },
        sendCommand,
      },
    };
    const params = { content: "hello", messageId: "message-1" };

    await expect(server.executeCommand("user_message", params)).rejects.toThrow(
      "delivery failed",
    );
    await expect(
      server.executeCommand("user_message", params),
    ).resolves.toBeUndefined();

    expect(sendCommand).toHaveBeenCalledTimes(2);
  });

  it("does not install an SSE controller canceled during initialization", async () => {
    let finishInitialization: (() => void) | undefined;
    const initializationGate = new Promise<void>((resolve) => {
      finishInitialization = resolve;
    });
    const controller = { send: vi.fn(), close: vi.fn() };
    const payload = { task_id: "task-1", run_id: "run-1" };
    type TestController = typeof controller;
    type TestPayload = typeof payload;
    const server = new PiAgentServer(config()) as unknown as {
      session: {
        payload: TestPayload;
        sseController: TestController | null;
      } | null;
      createSession(sessionPayload: TestPayload): Promise<void>;
      initializeSession(
        sessionPayload: TestPayload,
        sseController: TestController,
      ): Promise<void>;
      cancelSseController(sseController: TestController): void;
    };
    server.createSession = vi.fn(async (sessionPayload) => {
      await initializationGate;
      server.session = { payload: sessionPayload, sseController: null };
    });

    const initialization = server.initializeSession(payload, controller);
    server.cancelSseController(controller);
    finishInitialization?.();
    await initialization;

    expect(server.session?.sseController).toBeNull();
    expect(controller.send).not.toHaveBeenCalled();
  });

  it("preserves a replacement SSE controller when the old stream cancels", () => {
    const oldController = { send: vi.fn(), close: vi.fn() };
    const replacementController = { send: vi.fn(), close: vi.fn() };
    const server = new PiAgentServer(config()) as unknown as {
      session: { sseController: typeof replacementController } | null;
      cancelSseController(controller: typeof oldController): void;
    };
    server.session = { sseController: replacementController };

    server.cancelSseController(oldController);

    expect(server.session?.sseController).toBe(replacementController);

    server.cancelSseController(replacementController);

    expect(server.session?.sseController).toBeNull();
  });

  it("forwards native Pi RPC commands through the runtime", async () => {
    const sendCommand = vi.fn(async () => ({
      type: "response",
      command: "set_follow_up_mode",
      success: true,
    }));
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      executeCommand(
        method: string,
        params: Record<string, unknown>,
      ): Promise<unknown>;
    };
    server.session = { runtime: { client: {}, sendCommand } };
    const command = {
      type: "set_follow_up_mode",
      mode: "one-at-a-time",
    };

    const response = await server.executeCommand("pi/rpc", { command });

    expect(sendCommand).toHaveBeenCalledWith(command);
    expect(response).toEqual({
      type: "response",
      command: "set_follow_up_mode",
      success: true,
    });
  });

  it.each([
    ["queue_get", "getQueue"],
    ["queue_clear", "clearQueue"],
  ] as const)(
    "forwards %s through the private Pi host API",
    async (method, operation) => {
      const queue = {
        steering: ["fix this"],
        followUp: ["then summarize"],
      };
      const client = {
        getQueue: vi.fn(async () => queue),
        clearQueue: vi.fn(async () => queue),
      };
      const clearPendingQueuedUserMessages = vi.fn();
      const server = new PiAgentServer(config()) as unknown as {
        session: unknown;
        executeCommand(
          method: string,
          params: Record<string, unknown>,
        ): Promise<unknown>;
      };
      server.session = {
        runtime: { client, clearPendingQueuedUserMessages },
      };

      await expect(server.executeCommand(method, {})).resolves.toEqual(queue);
      expect(client[operation]).toHaveBeenCalledOnce();
      expect(clearPendingQueuedUserMessages).toHaveBeenCalledTimes(
        method === "queue_clear" ? 1 : 0,
      );
    },
  );

  it("waits for Pi to create the native session file before syncing", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-session-sync-"));
    const syncTaskSession = vi.fn(async () => "content-hash");
    const server = new PiAgentServer(config()) as unknown as {
      sessionFile: string;
      posthogAPI: { syncTaskSession: typeof syncTaskSession };
      syncTaskSession(): Promise<void>;
    };
    server.sessionFile = join(directory, "not-created.jsonl");
    server.posthogAPI = { syncTaskSession };

    await server.syncTaskSession();

    expect(syncTaskSession).not.toHaveBeenCalled();
    await rm(directory, { recursive: true });
  });

  it("syncs changed native session JSONL to durable task storage", async () => {
    const directory = await mkdtemp(join(tmpdir(), "pi-session-sync-"));
    const sessionFile = join(directory, "session.jsonl");
    const content = '{"type":"session"}\n';
    await writeFile(sessionFile, content);
    const syncTaskSession = vi.fn(async () => "content-hash");
    const server = new PiAgentServer(config()) as unknown as {
      sessionFile: string;
      posthogAPI: { syncTaskSession: typeof syncTaskSession };
      syncTaskSession(): Promise<void>;
    };
    server.sessionFile = sessionFile;
    server.posthogAPI = { syncTaskSession };

    await server.syncTaskSession();
    await server.syncTaskSession();

    expect(syncTaskSession).toHaveBeenCalledOnce();
    expect(syncTaskSession).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "sandbox-1",
      null,
      content,
      "task-run-token",
    );
    await rm(directory, { recursive: true });
  });

  it("publishes runtime-neutral Pi conversation events", () => {
    const send = vi.fn();
    const server = new PiAgentServer(config()) as unknown as {
      session: unknown;
      handleEvent(event: unknown): void;
    };
    server.session = { sseController: { send } };

    server.handleEvent({
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "hello" },
    });

    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "pi_event",
        event: expect.objectContaining({ type: "assistant_message_chunk" }),
      }),
    );
  });
});
