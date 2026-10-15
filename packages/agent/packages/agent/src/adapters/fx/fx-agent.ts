import {
  type Agent,
  type AgentSideConnection,
  type AuthenticateRequest,
  type CancelNotification,
  type Client,
  ClientSideConnection,
  type InitializeRequest,
  type InitializeResponse,
  type McpServer,
  type NewSessionRequest,
  type NewSessionResponse,
  ndJsonStream,
  type PromptRequest,
  type PromptResponse,
  RequestError,
  type RequestPermissionRequest,
  type SessionConfigOption,
  type SessionNotification,
  type SetSessionConfigOptionRequest,
  type SetSessionConfigOptionResponse,
  type SetSessionModeRequest,
  type SetSessionModeResponse,
  type Stream,
} from "@agentclientprotocol/sdk";
import { isMethod, POSTHOG_METHODS, steerDeclined } from "../../acp-extensions";
import type { ProcessSpawnedCallback } from "../../types";
import type { Logger } from "../../utils/logger";
import {
  nodeReadableToWebReadable,
  nodeWritableToWebWritable,
} from "../../utils/streams";
import { visiblePromptBlocks } from "../prompt-blocks";
import { type FxGatewayProxy, startFxGatewayProxy } from "./gateway-proxy";
import {
  FX_ASK_MODE,
  FX_POSTHOG_MODES,
  type FxPosthogMode,
  fromFxStopReason,
  fromFxUsage,
  fxMcpDescriptor,
  gatewayFailureError,
  toFxPosthogMode,
  toFxPrompt,
  toPosthogPermissionRequest,
  withPosthogMode,
  withPosthogToolMeta,
} from "./protocol";
import { writeFxProviderSettings } from "./settings";
import { type FxProcess, spawnFxAcpProcess } from "./spawn";

export interface FxOptions {
  cwd: string;
  binaryPath?: string;
  model: string;
  contextWindow?: number;
  supportsVision?: boolean;
  gatewayBaseUrl: string;
  gatewayApiKey: string;
  gatewayHeaders: Record<string, string>;
  instructions?: string;
}

export interface FxAcpAgentOptions extends FxOptions {
  logger: Logger;
  processCallbacks?: ProcessSpawnedCallback;
}

interface FxSteerMeta {
  fx?: { steer?: unknown; steering?: unknown };
}

interface FxSteeringChunkMeta {
  fx?: { steering?: { requestId?: unknown } };
}

interface PendingSteer {
  requestId?: string | number | null;
  consumed: () => void;
}

const MAX_SYSTEM_PROMPT_BYTES = 64 * 1024;

export class FxAcpAgent implements Agent {
  readonly adapterName = "fx";
  private fx: ClientSideConnection | null = null;
  private fxProcess: FxProcess | null = null;
  private proxy: FxGatewayProxy | null = null;
  private posthogMode: FxPosthogMode = "default";
  private configOptions: SessionConfigOption[] = [];
  private readonly mcpByToolCallId = new Map<
    string,
    { server: string; tool: string }
  >();
  private turnInFlight = false;
  private sessionId: string | null = null;
  private sessionCwd: string | null = null;
  private lastCompletionFailure: string | null = null;
  private readonly pendingSteers: PendingSteer[] = [];

  constructor(
    private readonly client: AgentSideConnection,
    private readonly options: FxAcpAgentOptions,
  ) {}

  async initialize(request: InitializeRequest): Promise<InitializeResponse> {
    const fx = await this.start();
    const response = await fx.initialize({
      protocolVersion: request.protocolVersion,
      clientCapabilities: {},
    });
    const fxSteering =
      (response.agentCapabilities?._meta as FxSteerMeta | undefined)?.fx
        ?.steering === true;
    return {
      ...response,
      agentCapabilities: {
        promptCapabilities: response.agentCapabilities?.promptCapabilities,
        mcpCapabilities: response.agentCapabilities?.mcpCapabilities,
        loadSession: false,
        ...(fxSteering && { _meta: { posthog: { steering: "native" } } }),
      },
    };
  }

  async newSession(params: NewSessionRequest): Promise<NewSessionResponse> {
    const fx = this.requireConnection();
    const requestedMode = (params._meta as { permissionMode?: unknown } | null)
      ?.permissionMode;
    const mode =
      requestedMode == null ? "default" : requireFxPosthogMode(requestedMode);
    const response = await fx.newSession({
      cwd: params.cwd,
      mcpServers: params.mcpServers,
      ...(this.options.instructions && {
        _meta: {
          fx: {
            systemPrompt: [
              {
                type: "text",
                text: this.truncatedInstructions(this.options.instructions),
              },
            ],
          },
        },
      }),
    });
    await this.ensureAskMode(response.sessionId, response.modes?.currentModeId);
    this.sessionId = response.sessionId;
    this.sessionCwd = params.cwd;
    this.posthogMode = mode;
    this.configOptions = response.configOptions ?? [];

    return {
      ...response,
      modes: {
        currentModeId: this.posthogMode,
        availableModes: FX_POSTHOG_MODES,
      },
      configOptions: withPosthogMode(this.configOptions, this.posthogMode),
    };
  }

  async prompt(params: PromptRequest): Promise<PromptResponse> {
    const fx = this.requireConnection();
    const meta = params._meta as
      | ({ steer?: unknown } & Parameters<typeof toFxPrompt>[1])
      | null
      | undefined;
    if (meta?.steer === true) {
      return this.steer(fx, params);
    }

    await this.echoUserMessage(params);
    this.turnInFlight = true;
    this.lastCompletionFailure = null;
    try {
      const response = await fx.prompt({
        sessionId: params.sessionId,
        prompt: toFxPrompt(params.prompt, meta),
      });
      const stopReason = fromFxStopReason(response.stopReason);
      const usage = fromFxUsage(response.usage);
      if (stopReason === "refusal" && this.lastCompletionFailure) {
        throw gatewayFailureError(this.lastCompletionFailure, usage);
      }
      return { stopReason, usage };
    } finally {
      this.turnInFlight = false;
    }
  }

  async cancel(params: CancelNotification): Promise<void> {
    await this.fx?.cancel({ sessionId: params.sessionId });
  }

  async setSessionMode(
    params: SetSessionModeRequest,
  ): Promise<SetSessionModeResponse> {
    await this.changeMode(params.sessionId, params.modeId);
    return {};
  }

  async setSessionConfigOption(
    params: SetSessionConfigOptionRequest,
  ): Promise<SetSessionConfigOptionResponse> {
    if (params.configId === "mode") {
      await this.changeMode(params.sessionId, params.value);
    } else {
      const response =
        await this.requireConnection().setSessionConfigOption(params);
      this.configOptions = response.configOptions;
    }
    return {
      configOptions: withPosthogMode(this.configOptions, this.posthogMode),
    };
  }

  async authenticate(_params: AuthenticateRequest): Promise<void> {
    throw RequestError.methodNotFound("authenticate");
  }

  async extMethod(
    method: string,
    params: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    if (!isMethod(method, POSTHOG_METHODS.REFRESH_SESSION)) {
      throw RequestError.methodNotFound(method);
    }
    if (!Array.isArray(params.mcpServers)) {
      throw RequestError.invalidParams(
        undefined,
        "refresh_session: mcpServers must be an array",
      );
    }
    if (!this.sessionId || !this.sessionCwd) {
      throw new RequestError(
        -32002,
        "Cannot refresh session before a session is started",
      );
    }
    if (this.turnInFlight) {
      throw new RequestError(
        -32002,
        "Cannot refresh session while a prompt turn is in flight",
      );
    }
    const response = await this.requireConnection().resumeSession({
      sessionId: this.sessionId,
      cwd: this.sessionCwd,
      mcpServers: params.mcpServers as McpServer[],
    });
    await this.ensureAskMode(this.sessionId, response.modes?.currentModeId);
    return { refreshed: true };
  }

  async closeSession(): Promise<void> {
    const fxProcess = this.fxProcess;
    this.fxProcess = null;
    this.fx = null;
    await fxProcess?.kill();
    await this.proxy?.stop();
    this.proxy = null;
  }

  private async start(): Promise<ClientSideConnection> {
    if (this.fx) return this.fx;
    const { logger } = this.options;

    this.proxy = await startFxGatewayProxy({
      upstreamBaseUrl: this.options.gatewayBaseUrl,
      upstreamApiKey: this.options.gatewayApiKey,
      headers: this.options.gatewayHeaders,
      logger,
      onCompletionResult: (failure) => {
        this.lastCompletionFailure = failure;
      },
    });
    await writeFxProviderSettings({
      baseUrl: this.proxy.baseUrl,
      model: this.options.model,
      contextWindow: this.options.contextWindow,
      supportsVision: this.options.supportsVision,
    });

    this.fxProcess = await spawnFxAcpProcess({
      binaryPath: this.options.binaryPath ?? "fx",
      cwd: this.options.cwd,
      model: this.options.model,
      gatewayKey: this.proxy.apiKey,
      logger,
      processCallbacks: this.options.processCallbacks,
    });
    const stream = ndJsonStream(
      nodeWritableToWebWritable(this.fxProcess.stdin),
      nodeReadableToWebReadable(this.fxProcess.stdout),
    );
    this.fx = new ClientSideConnection(() => this.upstreamClient(), {
      readable: stream.readable,
      writable: this.trackSteerRequests(stream.writable),
    });
    return this.fx;
  }

  private trackSteerRequests(writable: Stream["writable"]): Stream["writable"] {
    const writer = writable.getWriter();
    return new WritableStream({
      write: (message) => {
        if (
          "method" in message &&
          "id" in message &&
          message.method === "session/prompt" &&
          (message.params as { _meta?: FxSteerMeta } | undefined)?._meta?.fx
            ?.steer === true
        ) {
          const steer = this.pendingSteers.find(
            (pending) => pending.requestId === undefined,
          );
          if (steer) steer.requestId = message.id;
        }
        return writer.write(message);
      },
      close: () => writer.close(),
      abort: (reason) => writer.abort(reason),
    });
  }

  private upstreamClient(): Client {
    return {
      requestPermission: (params) =>
        this.client.requestPermission(this.withPermissionMeta(params)),
      sessionUpdate: (params) =>
        this.client.sessionUpdate(this.withUpdateMeta(params)),
    };
  }

  private withUpdateMeta(params: SessionNotification): SessionNotification {
    const { update } = params;
    if (update.sessionUpdate === "user_message_chunk") {
      const requestId = (update._meta as FxSteeringChunkMeta | undefined)?.fx
        ?.steering?.requestId;
      if (requestId !== undefined && requestId !== null) {
        this.pendingSteers
          .find((pending) => pending.requestId === requestId)
          ?.consumed();
      }
      return params;
    }
    if (update.sessionUpdate === "tool_call_update") {
      if (update.status === "completed" || update.status === "failed") {
        this.mcpByToolCallId.delete(update.toolCallId);
      }
      return params;
    }
    if (update.sessionUpdate !== "tool_call") return params;
    const mcp = fxMcpDescriptor(update._meta);
    if (!mcp) return params;
    this.mcpByToolCallId.set(update.toolCallId, mcp);
    return {
      ...params,
      update: {
        ...update,
        _meta: withPosthogToolMeta(update._meta, null, mcp),
      },
    };
  }

  private withPermissionMeta(
    params: RequestPermissionRequest,
  ): RequestPermissionRequest {
    const { toolCall } = params;
    const mcp =
      this.mcpByToolCallId.get(toolCall.toolCallId) ??
      fxMcpDescriptor(toolCall._meta);
    return toPosthogPermissionRequest(params, mcp);
  }

  private async ensureAskMode(
    sessionId: string,
    currentModeId: string | undefined,
  ): Promise<void> {
    if (currentModeId === FX_ASK_MODE) return;
    await this.requireConnection().setSessionMode({
      sessionId,
      modeId: FX_ASK_MODE,
    });
  }

  private async changeMode(sessionId: string, value: unknown): Promise<void> {
    const mode = requireFxPosthogMode(value);
    this.posthogMode = mode;
    await this.client
      .sessionUpdate({
        sessionId,
        update: { sessionUpdate: "current_mode_update", currentModeId: mode },
      })
      .catch(() => undefined);
    await this.client
      .sessionUpdate({
        sessionId,
        update: {
          sessionUpdate: "config_option_update",
          configOptions: withPosthogMode(this.configOptions, mode),
        },
      })
      .catch(() => undefined);
  }

  private async steer(
    fx: ClientSideConnection,
    params: PromptRequest,
  ): Promise<PromptResponse> {
    if (!this.turnInFlight) return steerDeclined("no_in_flight_turn");
    if (
      params.prompt.length === 0 ||
      params.prompt.some((block) => block.type !== "text")
    ) {
      return steerDeclined("turn_not_steerable");
    }
    const steer: PendingSteer = { consumed: () => {} };
    const consumed = new Promise<"consumed">((resolve) => {
      steer.consumed = () => resolve("consumed");
    });
    this.pendingSteers.push(steer);
    const reply = fx.prompt({
      sessionId: params.sessionId,
      prompt: params.prompt,
      _meta: { fx: { steer: true } },
    });
    try {
      const first = await Promise.race([consumed, reply]);
      if (first === "consumed") {
        reply.catch((error: unknown) => this.logSteerFailure(error));
        return { stopReason: "end_turn", _meta: { steer: true } };
      }
      if (
        (first._meta as FxSteerMeta | undefined)?.fx?.steering === "dropped"
      ) {
        return steerDeclined("turn_ended_first");
      }
      return {
        stopReason: fromFxStopReason(first.stopReason),
        usage: fromFxUsage(first.usage),
        _meta: { steer: true },
      };
    } catch (error) {
      this.logSteerFailure(error);
      return steerDeclined("turn_ended_first");
    } finally {
      this.pendingSteers.splice(this.pendingSteers.indexOf(steer), 1);
    }
  }

  private logSteerFailure(error: unknown): void {
    this.options.logger.warn("fx steer was not delivered", {
      error: error instanceof Error ? error.message : String(error),
    });
  }

  private async echoUserMessage(params: PromptRequest): Promise<void> {
    for (const block of visiblePromptBlocks(params.prompt)) {
      if (block.type !== "text" && block.type !== "image") continue;
      await this.client
        .sessionUpdate({
          sessionId: params.sessionId,
          update: { sessionUpdate: "user_message_chunk", content: block },
        })
        .catch(() => undefined);
    }
  }

  private truncatedInstructions(instructions: string): string {
    const bytes = Buffer.from(instructions);
    if (bytes.length <= MAX_SYSTEM_PROMPT_BYTES) return instructions;
    this.options.logger.warn("fx system prompt exceeds 64 KiB; truncating", {
      bytes: bytes.length,
    });
    return new TextDecoder()
      .decode(bytes.subarray(0, MAX_SYSTEM_PROMPT_BYTES))
      .replace(/�$/, "");
  }

  private requireConnection(): ClientSideConnection {
    if (!this.fx) {
      throw new Error("fx acp process is not running; call initialize first");
    }
    return this.fx;
  }
}

function requireFxPosthogMode(value: unknown): FxPosthogMode {
  const mode = toFxPosthogMode(value);
  if (!mode) {
    throw RequestError.invalidParams(
      undefined,
      `fx does not support mode: ${String(value)}`,
    );
  }
  return mode;
}
