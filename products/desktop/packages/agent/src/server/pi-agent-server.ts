import { randomUUID } from "node:crypto";
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import type { ServerType } from "@hono/node-server";
import { serve } from "@hono/node-server";
import type {
  AgentConversationEvent,
  StoredLogEntry,
  TaskRunArtifact,
} from "@posthog/shared";
import { serializeError } from "@posthog/shared";
import { Hono } from "hono";
import { z } from "zod/v4";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import { OtelRunTelemetry } from "../otel-telemetry";
import { createPiRpcClient, type PiRpcClient } from "../pi/rpc-client";
import { piRpcCommandSchema, type RpcCommand } from "../pi/rpc-transport";
import { PiRuntime } from "../pi/runtime";
import { PostHogAPIClient } from "../posthog-api";
import { resolveLlmGatewayUrl } from "../utils/gateway";
import { Logger } from "../utils/logger";
import { TaskRunEventStreamSender } from "./event-stream-sender";
import { type JwtPayload, JwtValidationError, validateJwt } from "./jwt";
import { jsonRpcRequestSchema } from "./schemas";
import type { AgentServerConfig } from "./types";

interface SseController {
  send(data: unknown): void;
  close(): void;
}

interface PiCloudSession {
  payload: JwtPayload;
  runtime: PiRuntime;
  sseController: SseController | null;
  unsubscribe: () => void;
}

const emptySchema = z.object({});
const MAX_PENDING_EVENTS = 1_000;
const MAX_PENDING_LOG_ENTRIES = 10_000;
const LOG_FLUSH_ENTRY_COUNT = 100;

const userMessageCommandSchema = z
  .object({
    content: z.string().min(1).optional(),
    artifacts: z.array(z.record(z.string(), z.unknown())).optional(),
    messageId: z.string().min(1).optional(),
    steer: z.boolean().optional(),
  })
  .refine(
    (params) => params.content || (params.artifacts?.length ?? 0) > 0,
    "Either content or artifacts are required",
  );

const commandSchemas = {
  user_message: userMessageCommandSchema,
  cancel: emptySchema,
  queue_get: emptySchema,
  queue_clear: emptySchema,
  "pi/rpc": z.object({ command: piRpcCommandSchema }),
} as const;

type PiCommandMethod = keyof typeof commandSchemas;

function updatedToolCallId(
  event: AgentConversationEvent | undefined,
): string | undefined {
  return event?.type === "tool_call_updated" ? event.toolCall.id : undefined;
}

function mergeToolCallUpdate(
  previous: AgentConversationEvent | undefined,
  next: AgentConversationEvent | undefined,
): AgentConversationEvent | undefined {
  if (
    previous?.type !== "tool_call_updated" ||
    next?.type !== "tool_call_updated" ||
    previous.toolCall.id !== next.toolCall.id
  ) {
    return next;
  }
  return {
    ...next,
    toolCall: { ...previous.toolCall, ...next.toolCall },
  };
}

export class PiAgentServer {
  private readonly app: Hono;
  private readonly logger = new Logger({
    debug: true,
    prefix: "[PiAgentServer]",
  });
  private readonly posthogAPI: PostHogAPIClient;
  private readonly eventStreamSender: TaskRunEventStreamSender | null;
  private server: ServerType | null = null;
  private session: PiCloudSession | null = null;
  private initializationPromise: Promise<void> | null = null;
  private pendingEvents: Record<string, unknown>[] = [];
  private sessionReadyBootMs?: number;
  private sessionInitMs?: number;
  private sessionFile: string | null = null;
  private lastSyncedSessionContent = "";
  private sessionContentSha256: string | null = null;
  private sessionSyncQueue: Promise<void> = Promise.resolve();
  private settledPersistenceQueue: Promise<void> = Promise.resolve();
  private pendingLogEntries: StoredLogEntry[] = [];
  private logFlushQueue: Promise<void> = Promise.resolve();
  private logFlushActive = false;
  private logFlushRequested = false;
  private readonly canceledSseControllers = new WeakSet<SseController>();

  constructor(private readonly config: AgentServerConfig) {
    this.posthogAPI = new PostHogAPIClient({
      apiUrl: config.apiUrl,
      projectId: config.projectId,
      getApiKey: () => config.apiKey,
      userAgent: `posthog/pi-cloud`,
    });
    this.eventStreamSender = config.eventIngestToken
      ? new TaskRunEventStreamSender({
          apiUrl: config.apiUrl,
          eventIngestBaseUrl: config.eventIngestBaseUrl,
          keepProxyStreamOpen: config.eventIngestKeepStreamOpen,
          projectId: config.projectId,
          taskId: config.taskId,
          runId: config.runId,
          token: config.eventIngestToken,
          logger: this.logger.child("EventIngest"),
          streamWindowMs: config.eventIngestStreamWindowMs,
        })
      : null;
    this.app = this.createApp();
  }

  private createRunTelemetry(
    payload: JwtPayload,
  ): OtelRunTelemetry | undefined {
    const { otelLogsUrl, otelLogsToken } = this.config;
    if (!otelLogsUrl || !otelLogsToken) return undefined;
    try {
      return new OtelRunTelemetry(
        {
          url: otelLogsUrl,
          token: otelLogsToken,
          tracesUrl: this.config.otelTracesUrl,
        },
        {
          taskId: payload.task_id,
          runId: payload.run_id,
          deviceType: "cloud",
          teamId: payload.team_id,
          userId: payload.user_id,
          distinctId: payload.distinct_id,
          adapter: "pi",
          mode: payload.mode ?? this.config.mode,
          agentVersion: this.config.version,
        },
        new Logger({ debug: false, prefix: "[OtelRunTelemetry]" }),
      );
    } catch (error) {
      this.logger.warn("Failed to initialize OTel run telemetry", error);
      return undefined;
    }
  }

  async start(): Promise<void> {
    await new Promise<void>((resolve) => {
      this.server = serve(
        { fetch: this.app.fetch, port: this.config.port },
        () => resolve(),
      );
    });

    const payload: JwtPayload = {
      task_id: this.config.taskId,
      run_id: this.config.runId,
      team_id: this.config.projectId,
      user_id: 0,
      distinct_id: "pi-agent-server",
      mode: this.config.mode,
    };
    await this.initializeSession(payload, null);
  }

  async stop(): Promise<void> {
    const session = this.session;
    if (session) {
      await session.runtime.client
        .abort()
        .catch((error) =>
          this.logger.debug(
            "Failed to abort Pi session during shutdown",
            error,
          ),
        );
      await session.runtime.client
        .waitForIdle(5_000)
        .catch((error) =>
          this.logger.debug(
            "Pi session did not become idle during shutdown",
            error,
          ),
        );
      await this.settledPersistenceQueue.catch((error) =>
        this.logger.error("Failed to persist settled Pi turn", error),
      );
      await this.syncTaskSession().catch((error) =>
        this.logger.error("Failed to sync Pi session during shutdown", error),
      );
      session.unsubscribe();
      await session.runtime.client
        .stop()
        .catch((error) =>
          this.logger.error("Failed to stop Pi client during shutdown", error),
        );
    }
    this.session = null;
    await this.flushConversationLog().catch((error) =>
      this.logger.error("Failed to persist Pi events during shutdown", error),
    );
    await this.eventStreamSender?.stop();
    this.server?.close();
    this.server = null;
  }

  async reportFatalError(error: unknown): Promise<void> {
    const message = error instanceof Error ? error.message : String(error);
    this.broadcast({
      type: "pi_event",
      timestamp: new Date().toISOString(),
      event: {
        type: "runtime_error",
        timestamp: Date.now(),
        errorType: "agent_server_crash",
        message,
      } satisfies AgentConversationEvent,
    });
    await this.settledPersistenceQueue.catch((syncError) =>
      this.logger.error(
        "Failed to persist settled Pi turn after crash",
        syncError,
      ),
    );
    await this.syncTaskSession().catch((syncError) =>
      this.logger.error("Failed to sync crashed Pi session", syncError),
    );
    await this.flushConversationLog().catch((syncError) =>
      this.logger.error("Failed to persist crashed Pi events", syncError),
    );
    await this.posthogAPI
      .updateTaskRun(this.config.taskId, this.config.runId, {
        status: "failed",
        error_message: `Pi agent server crashed: ${message}`,
      })
      .catch((updateError) =>
        this.logger.error(
          "Failed to mark crashed Pi run as failed",
          updateError,
        ),
      );
    await this.eventStreamSender?.stop();
  }

  private createApp(): Hono {
    const app = new Hono();

    app.get("/health", (context) =>
      context.json({
        status: "ok",
        hasSession: this.session !== null,
        bootMs: this.sessionReadyBootMs,
        sessionInitMs: this.sessionInitMs,
      }),
    );

    app.get("/events", async (context) => {
      let payload: JwtPayload;
      try {
        payload = this.authenticate(context.req.header.bind(context.req));
      } catch (error) {
        return context.json(
          { error: error instanceof Error ? error.message : "Invalid token" },
          401,
        );
      }

      const encoder = new TextEncoder();
      let keepalive: ReturnType<typeof setInterval> | null = null;
      let sseController: SseController | null = null;
      const stream = new ReadableStream({
        start: async (controller) => {
          sseController = {
            send: (data) =>
              controller.enqueue(
                encoder.encode(`data: ${JSON.stringify(data)}\n\n`),
              ),
            close: () => controller.close(),
          };
          keepalive = setInterval(() => {
            controller.enqueue(encoder.encode(": keepalive\n\n"));
          }, 25_000);
          await this.initializeSession(payload, sseController);
          if (this.session?.sseController !== sseController) {
            return;
          }
          this.replayPendingEvents();
          sseController.send({ type: "connected", run_id: payload.run_id });
        },
        cancel: () => {
          if (keepalive) {
            clearInterval(keepalive);
          }
          this.cancelSseController(sseController);
        },
      });

      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      });
    });

    app.post("/command", async (context) => {
      let payload: JwtPayload;
      try {
        payload = this.authenticate(context.req.header.bind(context.req));
      } catch (error) {
        return context.json(
          { error: error instanceof Error ? error.message : "Invalid token" },
          401,
        );
      }
      if (!this.session || this.session.payload.run_id !== payload.run_id) {
        return context.json({ error: "No active session for this run" }, 400);
      }

      const request = jsonRpcRequestSchema.safeParse(
        await context.req.json().catch(() => null),
      );
      if (!request.success) {
        return context.json({ error: "Invalid JSON-RPC request" }, 400);
      }

      const method = request.data.method as PiCommandMethod;
      const schema = commandSchemas[method];
      if (!schema) {
        return context.json({
          jsonrpc: "2.0",
          id: request.data.id,
          error: {
            code: -32601,
            message: `Unknown method: ${request.data.method}`,
          },
        });
      }
      const params = schema.safeParse(request.data.params ?? {});
      if (!params.success) {
        return context.json({
          jsonrpc: "2.0",
          id: request.data.id,
          error: { code: -32602, message: params.error.message },
        });
      }
      if (method === "pi/rpc") {
        const command = (params.data as { command: RpcCommand }).command;
        if (!command.id || command.id !== request.data.id) {
          return context.json({
            jsonrpc: "2.0",
            id: request.data.id,
            error: {
              code: -32602,
              message: "Pi command id must match the JSON-RPC request id",
            },
          });
        }
      }

      try {
        const result = await this.executeCommand(
          method,
          params.data as Record<string, unknown>,
        );
        return context.json({ jsonrpc: "2.0", id: request.data.id, result });
      } catch (error) {
        return context.json({
          jsonrpc: "2.0",
          id: request.data.id,
          error: {
            code: -32000,
            message: error instanceof Error ? error.message : "Unknown error",
          },
        });
      }
    });

    return app;
  }

  private async initializeSession(
    payload: JwtPayload,
    sseController: SseController | null,
  ): Promise<void> {
    if (this.session?.payload.run_id === payload.run_id) {
      this.installSseController(sseController);
      return;
    }
    if (this.initializationPromise) {
      await this.initializationPromise;
      this.installSseController(sseController);
      return;
    }

    const initializationPromise = this.createSession(payload);
    this.initializationPromise = initializationPromise;
    const initStartedAt = Date.now();
    try {
      await initializationPromise;
    } catch (error) {
      const telemetry = this.createRunTelemetry(payload);
      telemetry?.append(payload.run_id, {
        type: "notification",
        timestamp: new Date().toISOString(),
        notification: {
          jsonrpc: "2.0",
          method: POSTHOG_NOTIFICATIONS.INITIALIZATION_FAILED,
          params: {
            runtimeAdapter: "pi",
            initializationPhase: "session_setup",
            initMs: Date.now() - initStartedAt,
            requestedModel: this.config.model,
            gatewayConfigured: Boolean(
              process.env.LLM_GATEWAY_URL || this.config.apiUrl,
            ),
            errorType:
              error instanceof Error && error.name === "TimeoutError"
                ? "timeout"
                : "error",
          },
        },
      });
      await telemetry?.shutdown();
      this.logger.error("Pi session initialization failed", {
        runtimeAdapter: "pi",
        initializationPhase: "session_setup",
        initMs: Date.now() - initStartedAt,
        requestedModel: this.config.model ?? null,
        gatewayConfigured: Boolean(
          process.env.LLM_GATEWAY_URL || this.config.apiUrl,
        ),
        taskId: payload.task_id,
        taskRunId: payload.run_id,
        errorDetail: serializeError(error),
      });
      throw error;
    } finally {
      if (this.initializationPromise === initializationPromise) {
        this.initializationPromise = null;
      }
    }
    this.installSseController(sseController);
  }

  private async createSession(payload: JwtPayload): Promise<void> {
    const startedAt = Date.now();
    await this.waitForRepoReady();
    const cwd = this.config.repositoryPath ?? "/tmp/workspace";
    if (!this.config.sandboxId) {
      throw new Error("Pi task session persistence requires a sandbox ID");
    }
    const sessionStorage = await this.posthogAPI.getTaskSession(
      payload.task_id,
      payload.run_id,
    );
    const persistedSessionContent =
      await this.posthogAPI.downloadTaskSession(sessionStorage);
    const restoredSessionFile = persistedSessionContent
      ? join("/tmp", "posthog-pi-sessions", sessionStorage.id, "session.jsonl")
      : undefined;
    if (restoredSessionFile) {
      await mkdir(dirname(restoredSessionFile), { recursive: true });
      await writeFile(restoredSessionFile, persistedSessionContent, "utf8");
    }
    this.lastSyncedSessionContent = persistedSessionContent;
    this.sessionContentSha256 = sessionStorage.content_sha256;

    const client = createPiRpcClient({
      cliPath: this.config.piRpcHostPath,
      cwd,
      model: this.config.model,
      sessionFile: restoredSessionFile,
      providerOptions: {
        apiKey: this.config.apiKey,
        baseUrl: resolveLlmGatewayUrl(
          process.env.LLM_GATEWAY_URL,
          this.config.apiUrl,
        ),
      },
    });
    const runtime = new PiRuntime(client);
    const unsubscribeConversation = runtime.onConversationEvent((event) =>
      this.handleEvent(event),
    );
    const unsubscribeRuntime = runtime.onRuntimeEvent((event) => {
      if (event.type === "agent_settled") {
        this.settledPersistenceQueue = this.settledPersistenceQueue
          .then(() => this.persistSettledTurn())
          .catch((error) => {
            this.logger.error("Failed to persist settled Pi turn", error);
          });
      }
    });
    await client.start();
    if (this.config.reasoningEffort) {
      // Pi's ThinkingLevel has no ultracode notch; run it at its xhigh equivalent.
      await client.setThinkingLevel(
        this.config.reasoningEffort === "ultracode"
          ? "xhigh"
          : this.config.reasoningEffort,
      );
    }
    const runtimeState = await client.getState();
    this.sessionFile = runtimeState.sessionFile ?? restoredSessionFile ?? null;
    const unsubscribe = () => {
      unsubscribeConversation();
      unsubscribeRuntime();
    };

    this.session = { payload, runtime, sseController: null, unsubscribe };
    this.sessionReadyBootMs = Math.round(process.uptime() * 1000);
    this.sessionInitMs = Date.now() - startedAt;
    await this.posthogAPI.updateTaskRun(payload.task_id, payload.run_id, {
      status: "in_progress",
    });
    this.broadcast({
      type: "pi_run_started",
      timestamp: new Date().toISOString(),
      taskId: payload.task_id,
      runId: payload.run_id,
    });
  }

  private handleEvent(event: AgentConversationEvent): void {
    const id = randomUUID();
    this.broadcast({
      id,
      type: "pi_event",
      timestamp: new Date().toISOString(),
      event: { ...event, sourceId: id },
    });
    if (event.type === "queue_update") {
      void this.syncTaskSession().catch((error) =>
        this.logger.error("Failed to persist Pi queue state", error),
      );
    }
  }

  private async executeCommand(
    method: PiCommandMethod,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    const runtime = this.session?.runtime;
    if (!runtime) {
      throw new Error("No active Pi runtime");
    }
    const client = runtime.client;
    switch (method) {
      case "user_message":
        return this.deliverUserMessage(runtime, params);
      case "cancel":
        return client.abort();
      case "queue_get":
        return client.getQueue();
      case "queue_clear": {
        const queue = await client.clearQueue();
        runtime.clearPendingQueuedUserMessages();
        return queue;
      }
      case "pi/rpc":
        return runtime.sendCommand(params.command as RpcCommand);
    }
  }

  private async deliverUserMessage(
    runtime: PiRuntime,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    const artifacts = Array.isArray(params.artifacts)
      ? (params.artifacts as TaskRunArtifact[])
      : [];
    const message = await this.prepareUserMessage(
      typeof params.content === "string" ? params.content : "",
      artifacts,
    );
    return this.dispatchUserMessage(
      runtime,
      message.content,
      message.images,
      typeof params.messageId === "string" ? params.messageId : randomUUID(),
      params.steer === true,
    );
  }

  private async prepareUserMessage(
    content: string,
    artifacts: TaskRunArtifact[],
  ): Promise<{
    content: string;
    images: Parameters<PiRpcClient["prompt"]>[1];
  }> {
    const images: NonNullable<Parameters<PiRpcClient["prompt"]>[1]> = [];
    const filePaths: string[] = [];
    const attachmentDirectory = join(
      this.config.repositoryPath ?? "/tmp/workspace",
      ".posthog",
      "attachments",
    );

    for (const artifact of artifacts) {
      if (!artifact.storage_path) {
        continue;
      }
      const data = await this.posthogAPI.downloadArtifact(
        this.config.taskId,
        this.config.runId,
        artifact.storage_path,
      );
      if (!data) {
        throw new Error(`Failed to download attachment: ${artifact.name}`);
      }

      const mimeType = artifact.content_type ?? "application/octet-stream";
      if (mimeType.startsWith("image/")) {
        images.push({
          type: "image",
          data: Buffer.from(data).toString("base64"),
          mimeType,
          fileName: artifact.name,
        } as (typeof images)[number]);
        continue;
      }

      await mkdir(attachmentDirectory, { recursive: true });
      const fileName = `${artifact.id}-${basename(artifact.name)}`;
      const filePath = join(attachmentDirectory, fileName);
      await writeFile(filePath, Buffer.from(data));
      filePaths.push(filePath);
    }

    const attachmentText = filePaths.length
      ? `Attached files:\n${filePaths.map((filePath) => `- ${filePath}`).join("\n")}`
      : "";
    return {
      content: [content, attachmentText].filter(Boolean).join("\n\n"),
      images,
    };
  }

  private async dispatchUserMessage(
    runtime: PiRuntime,
    content: string,
    images: Parameters<PiRpcClient["prompt"]>[1],
    id: string,
    steer: boolean,
  ): Promise<unknown> {
    const state = await runtime.client.getState();
    if (state.isStreaming && steer) {
      return runtime.sendCommand({
        id,
        type: "steer",
        message: content,
        images,
      });
    }
    if (state.isStreaming) {
      return runtime.sendCommand({
        id,
        type: "follow_up",
        message: content,
        images,
      });
    }
    return runtime.sendCommand({
      id,
      type: "prompt",
      message: content,
      images,
    });
  }

  private installSseController(sseController: SseController | null): void {
    if (sseController && !this.canceledSseControllers.has(sseController)) {
      if (this.session) {
        this.session.sseController = sseController;
      }
    }
  }

  private cancelSseController(sseController: SseController | null): void {
    if (!sseController) {
      return;
    }
    this.canceledSseControllers.add(sseController);
    if (this.session?.sseController === sseController) {
      this.session.sseController = null;
    }
  }

  private async persistSettledTurn(): Promise<void> {
    await Promise.all([this.syncTaskSession(), this.flushConversationLog()]);
  }

  private syncTaskSession(): Promise<void> {
    const sync = this.sessionSyncQueue.then(async () => {
      if (!this.sessionFile) {
        return;
      }

      let content: string;
      try {
        content = await readFile(this.sessionFile, "utf8");
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") {
          return;
        }
        throw error;
      }
      if (content === this.lastSyncedSessionContent) {
        return;
      }

      if (!this.config.sandboxId || !this.config.taskRunSessionToken) {
        throw new Error(
          "Pi task session persistence requires sandbox credentials",
        );
      }
      this.sessionContentSha256 = await this.posthogAPI.syncTaskSession(
        this.config.taskId,
        this.config.runId,
        this.config.sandboxId,
        this.sessionContentSha256,
        content,
        this.config.taskRunSessionToken,
      );
      this.lastSyncedSessionContent = content;
    });
    this.sessionSyncQueue = sync.catch(() => undefined);
    return sync;
  }

  private broadcast(event: Record<string, unknown>): void {
    if (event.type === "pi_event" || event.type === "pi_run_started") {
      const logEntry: StoredLogEntry = {
        id: typeof event.id === "string" ? event.id : undefined,
        type: event.type,
        timestamp:
          typeof event.timestamp === "string" ? event.timestamp : undefined,
        event:
          event.type === "pi_event"
            ? (event.event as AgentConversationEvent)
            : undefined,
      };
      const toolCallId = updatedToolCallId(logEntry.event);
      const pendingLogIndex = toolCallId
        ? this.pendingLogEntries.findLastIndex(
            (entry) => updatedToolCallId(entry.event) === toolCallId,
          )
        : -1;
      if (pendingLogIndex >= 0) {
        const previous = this.pendingLogEntries[pendingLogIndex];
        this.pendingLogEntries[pendingLogIndex] = {
          ...logEntry,
          event: mergeToolCallUpdate(previous?.event, logEntry.event),
        };
      } else {
        this.pendingLogEntries.push(logEntry);
      }
      if (this.pendingLogEntries.length > MAX_PENDING_LOG_ENTRIES) {
        this.pendingLogEntries.splice(
          0,
          this.pendingLogEntries.length - MAX_PENDING_LOG_ENTRIES,
        );
      }
      if (
        event.type === "pi_run_started" ||
        this.pendingLogEntries.length >= LOG_FLUSH_ENTRY_COUNT ||
        (event.event as { type?: string } | undefined)?.type ===
          "turn_completed"
      ) {
        void this.flushConversationLog().catch((error) =>
          this.logger.error("Failed to persist Pi conversation events", error),
        );
      }
    }

    this.eventStreamSender?.enqueue(event);
    if (this.session?.sseController) {
      this.session.sseController.send(event);
    } else {
      const toolCallId = updatedToolCallId(
        event.type === "pi_event"
          ? (event.event as AgentConversationEvent)
          : undefined,
      );
      const pendingEventIndex = toolCallId
        ? this.pendingEvents.findLastIndex(
            (pending) =>
              pending.type === "pi_event" &&
              updatedToolCallId(
                pending.event as AgentConversationEvent | undefined,
              ) === toolCallId,
          )
        : -1;
      if (pendingEventIndex >= 0) {
        const previous = this.pendingEvents[pendingEventIndex];
        this.pendingEvents[pendingEventIndex] = {
          ...event,
          event: mergeToolCallUpdate(
            previous?.event as AgentConversationEvent | undefined,
            event.event as AgentConversationEvent | undefined,
          ),
        };
      } else {
        this.pendingEvents.push(event);
      }
      if (this.pendingEvents.length > MAX_PENDING_EVENTS) {
        this.pendingEvents.splice(
          0,
          this.pendingEvents.length - MAX_PENDING_EVENTS,
        );
      }
    }
  }

  private flushConversationLog(): Promise<void> {
    if (this.logFlushActive) {
      this.logFlushRequested = true;
      return this.logFlushQueue;
    }
    if (this.pendingLogEntries.length === 0) {
      return this.logFlushQueue;
    }

    this.logFlushActive = true;
    const flush = (async () => {
      do {
        this.logFlushRequested = false;
        const entries = this.pendingLogEntries;
        this.pendingLogEntries = [];
        if (entries.length === 0) {
          return;
        }
        try {
          await this.posthogAPI.appendTaskRunLog(
            this.config.taskId,
            this.config.runId,
            entries,
          );
        } catch (error) {
          this.pendingLogEntries = [
            ...entries,
            ...this.pendingLogEntries,
          ].slice(-MAX_PENDING_LOG_ENTRIES);
          throw error;
        }
      } while (
        this.logFlushRequested ||
        this.pendingLogEntries.length >= LOG_FLUSH_ENTRY_COUNT
      );
    })().finally(() => {
      this.logFlushActive = false;
    });

    this.logFlushQueue = flush.catch(() => undefined);
    return flush;
  }

  private replayPendingEvents(): void {
    const controller = this.session?.sseController;
    if (!controller) {
      return;
    }
    const events = this.pendingEvents;
    this.pendingEvents = [];
    for (const event of events) {
      controller.send(event);
    }
  }

  private authenticate(
    getHeader: (name: string) => string | undefined,
  ): JwtPayload {
    const authHeader = getHeader("authorization");
    if (!authHeader?.startsWith("Bearer ")) {
      throw new JwtValidationError(
        "Missing authorization header",
        "invalid_token",
      );
    }
    const payload = validateJwt(authHeader.slice(7), this.config.jwtPublicKey);
    this.assertConfiguredRun(payload);
    return payload;
  }

  private assertConfiguredRun(payload: JwtPayload): void {
    if (
      payload.task_id !== this.config.taskId ||
      payload.run_id !== this.config.runId ||
      payload.team_id !== this.config.projectId
    ) {
      throw new JwtValidationError(
        "Token does not match the configured task run",
        "invalid_token",
      );
    }
  }

  private async waitForRepoReady(): Promise<void> {
    const path = this.config.repoReadyFile;
    if (!path) {
      return;
    }
    const deadline = Date.now() + 10 * 60_000;
    while (Date.now() < deadline) {
      try {
        await access(path);
        return;
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
    }
    throw new Error(`Repository readiness file was not created: ${path}`);
  }
}
