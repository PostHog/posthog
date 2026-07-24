import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  type AgentSideConnection,
  type ClientCapabilities,
  type ForkSessionRequest,
  type ForkSessionResponse,
  type InitializeRequest,
  type InitializeResponse,
  type ListSessionsRequest,
  type ListSessionsResponse,
  type LoadSessionRequest,
  type LoadSessionResponse,
  type NewSessionRequest,
  type NewSessionResponse,
  type PromptRequest,
  type PromptResponse,
  RequestError,
  type ResumeSessionRequest,
  type ResumeSessionResponse,
  type SessionConfigOption,
  type SessionConfigOptionCategory,
  type SessionConfigSelectOption,
  type SessionModeState,
  type SetSessionConfigOptionRequest,
  type SetSessionConfigOptionResponse,
  type SetSessionModeRequest,
  type SetSessionModeResponse,
  type Usage,
} from "@agentclientprotocol/sdk";
import {
  type CanUseTool,
  type FastModeState,
  getSessionInfo,
  getSessionMessages,
  listSessions,
  type McpSdkServerConfigWithInstance,
  type McpServerConfig,
  type Options,
  type Query,
  query,
  type SDKUserMessage,
  type SlashCommand,
} from "@anthropic-ai/claude-agent-sdk";
import { serializeError } from "@posthog/shared";
import { v7 as uuidv7 } from "uuid";
import packageJson from "../../../package.json" with { type: "json" };
import {
  isMethod,
  POSTHOG_METHODS,
  POSTHOG_NOTIFICATIONS,
} from "../../acp-extensions";
import {
  createEnrichment,
  type Enrichment,
  type FileEnrichmentDeps,
} from "../../enrichment/file-enricher";
import { PostHogAPIClient } from "../../posthog-api";
import { resolvePostHogExecPermissionRegex } from "../../posthog-exec-permission";
import {
  classifyPostHogExecCall,
  isUnclassifiedPostHogSubTool,
  POSTHOG_PRODUCTS,
  type PostHogProductId,
} from "../../posthog-products";
import type { PostHogAPIConfig } from "../../types";
import {
  isCloudRun,
  unreachable,
  withAbort,
  withTimeout,
} from "../../utils/common";
import { resolveGithubToken } from "../../utils/github-token";
import { Logger } from "../../utils/logger";
import { Pushable } from "../../utils/streams";
import { BaseAcpAgent } from "../base-acp-agent";
import { LOCAL_TOOLS_MCP_NAME, type LocalToolCtx } from "../local-tools";
import { resolveSpokenNarration, resolveTaskId } from "../session-meta";
import {
  buildBreakdown,
  emptyBaseline,
  estimateMcpTokens,
  estimateRulesTokens,
  estimateSkillsTokens,
  estimateSystemPrompt,
} from "./context-breakdown";
import { isSteerMeta, promptToClaude } from "./conversion/acp-to-sdk";
import {
  handleResultMessage,
  handleStreamEvent,
  handleSystemMessage,
  handleUserAssistantMessage,
} from "./conversion/sdk-to-acp";
import {
  rehydrateTaskState,
  type TaskState,
  taskStateToPlanEntries,
} from "./conversion/task-state";
import type { EnrichedReadCache } from "./hooks";
import { createLocalToolsMcpServer } from "./mcp/local-tools";
import {
  clearMcpToolMetadataCache,
  fetchMcpToolMetadata,
  getCachedMcpTools,
  getConnectedMcpServerNames,
  setMcpToolApprovalStates,
} from "./mcp/tool-metadata";
import { canUseTool } from "./permissions/permission-handlers";
import { getAvailableSlashCommands } from "./session/commands";
import { parseMcpServers } from "./session/mcp-config";
import {
  applyAvailableModelsAllowlist,
  resolveInitialModelId,
} from "./session/model-config";
import {
  DEFAULT_EFFORT,
  DEFAULT_MODEL,
  fastModeStateEnabled,
  getEffortOptions,
  resolveEffortForModel,
  resolveModelPreference,
  supports1MContext,
  supportsFastMode,
  supportsMcpInjection,
  toSdkModelId,
} from "./session/models";
import {
  buildSessionOptions,
  buildSystemPrompt,
  type GatewayEnv,
  type ProcessSpawnedInfo,
} from "./session/options";
import { SettingsManager } from "./session/settings";
import {
  CODE_EXECUTION_MODES,
  type CodeExecutionMode,
  getAvailableModes,
  toSdkPermissionMode,
} from "./tools";
import type {
  BackgroundTerminal,
  EffortLevel,
  NewSessionMeta,
  SDKMessageFilter,
  Session,
  ToolUpdateMeta,
  ToolUseCache,
  ToolUseStreamCache,
  Turn,
} from "./types";

const SESSION_VALIDATION_TIMEOUT_MS = 30_000;

// Pre-prompt self-heal runs on every cloud turn; bound the status RPC so a
// wedged control channel can't stall the turn.
const MCP_STATUS_TIMEOUT_MS = 5_000;

const DEFAULT_FORCE_CANCEL_GRACE_MS = 30_000;

const SESSION_ENDED_MESSAGE =
  "The Claude Agent session has ended. Please start a new session.";

const MAX_TITLE_LENGTH = 256;
const LOCAL_ONLY_COMMANDS = new Set(["/context", "/heapdump", "/extra-usage"]);

function isSdkMcpServer(
  cfg: McpServerConfig,
): cfg is McpSdkServerConfigWithInstance {
  return cfg.type === "sdk";
}

function externalMcpServers(
  servers: Record<string, McpServerConfig> | undefined,
): Record<string, McpServerConfig> {
  return Object.fromEntries(
    Object.entries(servers ?? {}).filter(([, cfg]) => !isSdkMcpServer(cfg)),
  );
}

// Best-effort: silent on ENOENT, logs other errors so permission failures
// aren't masked.
function readClaudeMdQuietly(cwd: string, logger: Logger): string | undefined {
  try {
    return fs.readFileSync(path.join(cwd, "CLAUDE.md"), "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code !== "ENOENT") {
      logger.warn("Failed to read CLAUDE.md for context breakdown", {
        cwd,
        error: err instanceof Error ? err.message : String(err),
      });
    }
    return undefined;
  }
}

function collectKnownSlashCommands(
  commands: SlashCommand[] | undefined,
): Set<string> {
  const names = new Set<string>();
  if (!commands) return names;
  for (const cmd of commands) {
    if (cmd.name) names.add(cmd.name);
  }
  return names;
}

function sanitizeTitle(text: string): string {
  const sanitized = text
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (sanitized.length <= MAX_TITLE_LENGTH) {
    return sanitized;
  }
  return `${sanitized.slice(0, MAX_TITLE_LENGTH - 1)}…`;
}

function shouldEmitRawMessage(
  config: boolean | SDKMessageFilter[],
  message: { type: string; subtype?: string },
): boolean {
  if (config === true) return true;
  if (config === false) return false;
  return config.some(
    (f) =>
      f.type === message.type &&
      (f.subtype === undefined || f.subtype === message.subtype),
  );
}

async function fetchContextUsedTokens(
  sdkQuery: Query,
  logger: Logger,
): Promise<number | null> {
  try {
    const usage = await sdkQuery.getContextUsage();
    return usage.totalTokens;
  } catch (error) {
    logger.error("Failed to fetch context usage from SDK:", error);
    return null;
  }
}

export interface ClaudeAcpAgentOptions {
  onProcessSpawned?: (info: ProcessSpawnedInfo) => void;
  onProcessExited?: (pid: number) => void;
  onMcpServersReady?: (serverNames: string[]) => void;
  onStructuredOutput?: (output: Record<string, unknown>) => Promise<void>;
  posthogApiConfig?: PostHogAPIConfig;
  /** Explicit gateway config — avoids global process.env mutation across concurrent sessions. */
  gatewayEnv?: GatewayEnv;
}

export class ClaudeAcpAgent extends BaseAcpAgent {
  readonly adapterName = "claude";
  declare session: Session;
  toolUseCache: ToolUseCache;
  /** Tool_use ids already surfaced as a `tool_call` (permission requests emit
   *  eagerly); the second emitter refines instead of duplicating. */
  emittedToolCalls: Set<string>;
  toolUseStreamCache: ToolUseStreamCache;
  backgroundTerminals: { [key: string]: BackgroundTerminal } = {};
  clientCapabilities?: ClientCapabilities;
  forceCancelGraceMs: number = DEFAULT_FORCE_CANCEL_GRACE_MS;
  private options?: ClaudeAcpAgentOptions;
  private enrichment?: Enrichment;
  private enrichedReadCache: EnrichedReadCache = new Map();

  constructor(client: AgentSideConnection, options?: ClaudeAcpAgentOptions) {
    super(client);
    this.options = options;
    this.toolUseCache = {};
    this.emittedToolCalls = new Set();
    this.toolUseStreamCache = new Map();
    this.logger = new Logger({ debug: true, prefix: "[ClaudeAcpAgent]" });
    this.enrichment = createEnrichment(options?.posthogApiConfig, this.logger);
  }

  protected getEnrichmentDeps(): FileEnrichmentDeps | undefined {
    return this.enrichment?.deps;
  }

  override async closeSession(): Promise<void> {
    try {
      await super.closeSession();
    } finally {
      this.enrichment?.dispose();
      this.enrichment = undefined;
      this.enrichedReadCache.clear();
    }
  }

  async initialize(request: InitializeRequest): Promise<InitializeResponse> {
    this.clientCapabilities = request.clientCapabilities;

    return {
      protocolVersion: 1,
      agentCapabilities: {
        promptCapabilities: {
          image: true,
          embeddedContext: true,
        },
        mcpCapabilities: {
          http: true,
          sse: true,
        },
        loadSession: true,
        sessionCapabilities: {
          additionalDirectories: {},
          list: {},
          fork: {},
          resume: {},
        },
        _meta: {
          posthog: {
            resumeSession: true,
            steering: "native",
          },
          claudeCode: {
            promptQueueing: true,
          },
        },
      },
      agentInfo: {
        name: packageJson.name,
        title: "Claude Agent",
        version: packageJson.version,
      },
      authMethods: [],
    };
  }

  async newSession(params: NewSessionRequest): Promise<NewSessionResponse> {
    // Upstream Claude Code renames .claude.json to .claude.json.backup on logout.
    // If the backup exists but the original doesn't, the user is logged out.
    if (
      fs.existsSync(path.resolve(os.homedir(), ".claude.json.backup")) &&
      !fs.existsSync(path.resolve(os.homedir(), ".claude.json"))
    ) {
      throw RequestError.authRequired();
    }

    const response = await this.createSession(
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers ?? [],
        additionalDirectories: params.additionalDirectories,
        _meta: params._meta,
      },
      {
        // Revisit these meta values once we support resume
        resume: (params._meta as NewSessionMeta | undefined)?.claudeCode
          ?.options?.resume as string | undefined,
      },
    );

    return response;
  }

  async unstable_forkSession(
    params: ForkSessionRequest,
  ): Promise<ForkSessionResponse> {
    return this.createSession(
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers ?? [],
        additionalDirectories: params.additionalDirectories,
        _meta: params._meta,
      },
      { resume: params.sessionId, forkSession: true },
    );
  }

  async resumeSession(
    params: ResumeSessionRequest,
  ): Promise<ResumeSessionResponse> {
    // Reuse existing session if it matches
    const existing = this.getExistingSessionState(params.sessionId);
    if (existing) return existing;

    const response = await this.createSession(
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers ?? [],
        additionalDirectories: params.additionalDirectories,
        _meta: params._meta,
      },
      {
        resume: params.sessionId,
      },
    );

    await this.rehydrateTaskStateFromJsonl(params.sessionId);

    return response;
  }

  async loadSession(params: LoadSessionRequest): Promise<LoadSessionResponse> {
    // Reuse existing session if it matches
    const existing = this.getExistingSessionState(params.sessionId);
    if (existing) return existing;

    const response = await this.createSession(
      {
        cwd: params.cwd,
        mcpServers: params.mcpServers ?? [],
        additionalDirectories: params.additionalDirectories,
        _meta: params._meta,
      },
      { resume: params.sessionId, skipBackgroundFetches: true },
    );

    await this.replaySessionHistory(params.sessionId);

    // Send available commands after replay so they don't interleave with history
    this.deferBackgroundFetches(this.session.query);

    return {
      modes: response.modes,
      configOptions: response.configOptions,
    };
  }

  async listSessions(
    params: ListSessionsRequest,
  ): Promise<ListSessionsResponse> {
    const sdkSessions = await listSessions({ dir: params.cwd ?? undefined });
    const sessions = [];

    for (const session of sdkSessions) {
      if (!session.cwd) continue;
      sessions.push({
        sessionId: session.sessionId,
        cwd: session.cwd,
        title: sanitizeTitle(session.customTitle || session.summary || ""),
        updatedAt: new Date(session.lastModified).toISOString(),
      });
    }
    return {
      sessions,
    };
  }

  async unstable_listSessions(
    params: ListSessionsRequest,
  ): Promise<ListSessionsResponse> {
    return this.listSessions(params);
  }

  async prompt(params: PromptRequest): Promise<PromptResponse> {
    const userMessage = promptToClaude(params);
    const promptUuid = randomUUID();
    userMessage.uuid = promptUuid;
    let isLocalOnlyCommand = false;

    // Detect local-only slash commands that return results without model invocation
    const msgContent = userMessage.message.content;
    let firstTextPart = "";
    if (typeof msgContent === "string") {
      firstTextPart = msgContent;
    } else if (Array.isArray(msgContent)) {
      for (const block of msgContent) {
        if ("type" in block && block.type === "text" && "text" in block) {
          firstTextPart = block.text as string;
          break;
        }
      }
    }
    const commandMatch = firstTextPart.match(/^(\/\S+)/);
    if (commandMatch && LOCAL_ONLY_COMMANDS.has(commandMatch[1])) {
      isLocalOnlyCommand = true;
    }

    if (commandMatch && !isLocalOnlyCommand) {
      await this.refreshSlashCommandsForPrompt(commandMatch[1]);
    }

    if (this.session.queryClosed) {
      throw RequestError.internalError(undefined, SESSION_ENDED_MESSAGE);
    }

    const hasInFlightTurns =
      this.session.activeTurn !== null || this.session.turnQueue.length > 0;

    const isSteer = isSteerMeta(params._meta);
    if (hasInFlightTurns && isSteer) {
      // Fold into the running turn (promptToClaude tagged it priority:"next");
      // the benign end_turn is ignored by clients, which key off _meta.steer.
      const owner =
        this.session.activeTurn ??
        this.session.turnQueue.find((turn) => !turn.settled);
      owner?.pendingSteerUuids.add(promptUuid);
      this.session.input.push(userMessage);
      await this.broadcastUserMessage(params);
      return { stopReason: "end_turn", _meta: { steer: true } };
    }
    if (isSteer) {
      return { stopReason: "end_turn", _meta: { steer: false } };
    }

    if (!hasInFlightTurns && !isLocalOnlyCommand) {
      // Reconnect the signed-commit server before the turn (guard hook backstops).
      await this.ensureLocalToolsConnected("pre-prompt");
    }

    if (this.session.lastContextWindowSize == null) {
      this.session.lastContextWindowSize = this.getContextWindowForModel(
        this.session.modelId ?? "",
      );
      this.logger.debug("Initial context window size from gateway", {
        modelId: this.session.modelId,
        contextWindowSize: this.session.lastContextWindowSize,
      });
    }

    const turn: Turn = {
      promptUuid,
      pendingSteerUuids: new Set(),
      isLocalOnlyCommand,
      commandName: commandMatch?.[1],
      broadcast: () => this.broadcastUserMessage(params),
      settled: false,
      resolve: () => {},
      reject: () => {},
    };
    const response = new Promise<PromptResponse>((resolve, reject) => {
      turn.resolve = resolve;
      turn.reject = reject;
    });

    this.session.turnQueue.push(turn);
    this.session.input.push(userMessage);
    this.ensureConsumer(params.sessionId);
    return response;
  }

  private ensureConsumer(sessionId: string): void {
    const session = this.session;
    if (session.consumer) {
      return;
    }
    session.cancelController = new AbortController();
    session.consumer = this.runConsumer(session, sessionId);
    session.consumer.catch((error) => {
      this.logger.error("Consumer terminated unexpectedly", {
        sessionId,
        error: error instanceof Error ? error.message : String(error),
      });
    });
  }

  private cancelledResponse(): PromptResponse {
    return {
      stopReason: "cancelled",
      _meta: this.session.interruptReason
        ? { interruptReason: this.session.interruptReason }
        : undefined,
    };
  }

  /** Idempotent teardown once the query iterator is unrevivable. */
  private closeQueryStream(session: Session): void {
    session.queryClosed = true;
    session.consumer = undefined;
    if (session.forceCancelTimer) {
      clearTimeout(session.forceCancelTimer);
      session.forceCancelTimer = undefined;
    }
    session.cancelController = undefined;
    session.settingsManager.dispose();
    session.input.end();
    this.toolUseStreamCache.clear();
    this.emittedToolCalls.clear();
  }

  /** Long-lived consumer of the session's SDK query stream: forwards every
   *  message (including between-turn output) and settles Turn deferreds. */
  private async runConsumer(
    session: Session,
    sessionId: string,
  ): Promise<void> {
    // refreshSession swaps query/input in place and bumps the generation; a
    // retired consumer must exit without tearing the refreshed session down.
    const query = session.query;
    const generation = session.queryGeneration;
    const refreshed = () =>
      this.session !== session ||
      session.query !== query ||
      session.queryGeneration !== generation;

    // Per-turn scratch, reset on activation.
    let lastAssistantTotalUsage: number | null = null;
    let lastRefusalExplanation: string | null = null;
    let lastRefusalCategory: string | null = null;
    let lastStreamUsage = {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_input_tokens: 0,
      cache_creation_input_tokens: 0,
    };
    // Tracks whether we're inside a compaction. The SDK emits the terminal
    // `status` (compact_result success/failed) twice for a single failed
    // compaction, and the two messages are indistinguishable, so we report the
    // outcome only while a compaction is in progress, then clear this. A fresh
    // `compacting` status sets it again, so every distinct compaction (e.g.
    // repeated auto-compactions in a long turn) is still shown.
    let compactionInProgress = false;
    let stopReason: PromptResponse["stopReason"] = "end_turn";

    // Read live: model switches reset session.lastContextWindowSize.
    const windowSize = () =>
      this.session.lastContextWindowSize ??
      this.getContextWindowForModel(this.session.modelId ?? "");

    const supportsTerminalOutput =
      (
        this.clientCapabilities?._meta as
          | ClientCapabilities["_meta"]
          | undefined
      )?.terminal_output === true;

    const context = {
      session,
      sessionId,
      client: this.client,
      toolUseCache: this.toolUseCache,
      emittedToolCalls: this.emittedToolCalls,
      toolUseStreamCache: this.toolUseStreamCache,
      fileContentCache: this.fileContentCache,
      enrichedReadCache: this.enrichedReadCache,
      logger: this.logger,
      supportsTerminalOutput,
      // Consumer-lived: turn activation can fire mid-message, so this must
      // not reset per turn (it is cleared per message instead).
      streamedAssistantBlocks: { blocks: [] },
    };

    const sessionUsage = (): Usage => {
      const acc = session.accumulatedUsage;
      return {
        inputTokens: acc.inputTokens,
        outputTokens: acc.outputTokens,
        cachedReadTokens: acc.cachedReadTokens,
        cachedWriteTokens: acc.cachedWriteTokens,
        totalTokens:
          acc.inputTokens +
          acc.outputTokens +
          acc.cachedReadTokens +
          acc.cachedWriteTokens,
      };
    };

    const recordContextUsage = (nextTotal: number): boolean => {
      if (nextTotal <= 0 || nextTotal === lastAssistantTotalUsage) {
        return false;
      }
      const knownTotal = Math.max(
        lastAssistantTotalUsage ?? 0,
        session.contextUsed ?? 0,
      );
      if (nextTotal < knownTotal) {
        return false;
      }
      lastAssistantTotalUsage = nextTotal;
      return true;
    };

    const resetTurnScratch = () => {
      lastAssistantTotalUsage = null;
      lastRefusalExplanation = null;
      lastRefusalCategory = null;
      lastStreamUsage = {
        input_tokens: 0,
        output_tokens: 0,
        cache_read_input_tokens: 0,
        cache_creation_input_tokens: 0,
      };
      compactionInProgress = false;
      stopReason = "end_turn";
      // sessionResources is intentionally NOT reset — the products list
      // accumulates across the whole session and is deduped, not per-turn.
      session.accumulatedUsage = {
        inputTokens: 0,
        outputTokens: 0,
        cachedReadTokens: 0,
        cachedWriteTokens: 0,
      };
    };

    const activateTurn = async (turn: Turn) => {
      session.activeTurn = turn;
      session.cancelled = false;
      session.interruptReason = undefined;
      session.pendingOrphanResults = 0;
      resetTurnScratch();
      try {
        await turn.broadcast();
      } catch (error) {
        this.logger.warn("Failed to broadcast user message", {
          sessionId,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    };

    // Promote the queue head for echo-less results (local-only commands,
    // compaction), skipping any orphan results owed by cancelled-while-queued
    // turns so they can't be misattributed to a later prompt.
    const ensureActiveTurn = async () => {
      if (session.activeTurn) {
        return;
      }
      const head = session.turnQueue.find((t) => !t.settled);
      if (!head) {
        return;
      }
      if (session.pendingOrphanResults > 0) {
        session.pendingOrphanResults--;
        return;
      }
      await activateTurn(head);
    };

    const settleActive = (result: PromptResponse) => {
      const turn = session.activeTurn;
      if (!turn || turn.settled) {
        return;
      }
      turn.settled = true;
      if (session.forceCancelTimer) {
        clearTimeout(session.forceCancelTimer);
        session.forceCancelTimer = undefined;
      }
      session.turnQueue = session.turnQueue.filter((t) => t !== turn);
      session.activeTurn = null;
      turn.resolve(result);
    };

    // Reject the active turn without tearing down the consumer.
    const failActive = (error: unknown) => {
      if (session.forceCancelTimer) {
        clearTimeout(session.forceCancelTimer);
        session.forceCancelTimer = undefined;
      }
      const turn = session.activeTurn;
      if (!turn || turn.settled) {
        return;
      }
      turn.settled = true;
      session.turnQueue = session.turnQueue.filter((t) => t !== turn);
      session.activeTurn = null;
      this.toolUseStreamCache.clear();
      turn.reject(error);
    };

    // Reject every in-flight turn when the stream dies.
    const failAllTurns = (error: unknown) => {
      if (session.forceCancelTimer) {
        clearTimeout(session.forceCancelTimer);
        session.forceCancelTimer = undefined;
      }
      const turns = session.activeTurn
        ? [
            session.activeTurn,
            ...session.turnQueue.filter((t) => t !== session.activeTurn),
          ]
        : [...session.turnQueue];
      session.activeTurn = null;
      session.turnQueue = [];
      this.toolUseStreamCache.clear();
      for (const turn of turns) {
        if (!turn.settled) {
          turn.settled = true;
          turn.reject(error);
        }
      }
    };

    let cancelController = session.cancelController as AbortController;

    try {
      while (true) {
        const nextMessage = query.next();
        const next = await withAbort(nextMessage, cancelController.signal);
        if (next.result === "aborted" || cancelController.signal.aborted) {
          // Abandon the in-flight next(), swallowing any later rejection.
          void nextMessage.catch((err) =>
            this.logger.warn("in-flight query.next() rejected after cancel", {
              sessionId,
              error: err instanceof Error ? err.message : String(err),
            }),
          );
          settleActive(this.cancelledResponse());
          this.toolUseStreamCache.clear();
          if (refreshed() || session.queryClosed) {
            return;
          }
          cancelController = new AbortController();
          session.cancelController = cancelController;
          continue;
        }
        const { value: message, done } = next.value;

        if (done || !message) {
          if (refreshed()) {
            return;
          }
          settleActive(
            session.cancelled
              ? this.cancelledResponse()
              : { stopReason, usage: sessionUsage() },
          );
          // Queued turns the SDK never started produced no output; reject
          // them rather than report a success.
          for (const queued of [...session.turnQueue]) {
            if (!queued.settled) {
              queued.settled = true;
              queued.reject(
                RequestError.internalError(undefined, SESSION_ENDED_MESSAGE),
              );
            }
          }
          session.turnQueue = [];
          this.closeQueryStream(session);
          return;
        }

        if (
          session.emitRawSDKMessages &&
          shouldEmitRawMessage(session.emitRawSDKMessages, message)
        ) {
          await this.client.extNotification("_claude/sdkMessage", {
            sessionId,
            message: message as Record<string, unknown>,
          });
        }

        switch (message.type) {
          case "system":
            if (message.subtype === "init") {
              await this.syncFastModeState(message.fast_mode_state);
            }
            if (message.subtype === "compact_boundary") {
              await ensureActiveTurn();
              const usedTokens = await withAbort(
                fetchContextUsedTokens(query, this.logger),
                cancelController.signal,
              );
              if (usedTokens.result === "success" && usedTokens.value != null) {
                lastAssistantTotalUsage = usedTokens.value;
                session.contextUsed = usedTokens.value;
                session.contextSize = windowSize();
                await this.client.sessionUpdate({
                  sessionId,
                  update: {
                    sessionUpdate: "usage_update",
                    used: lastAssistantTotalUsage,
                    size: windowSize(),
                  },
                });
              }
            }
            if (message.subtype === "commands_changed") {
              session.knownSlashCommands = collectKnownSlashCommands(
                message.commands,
              );
              const available = getAvailableSlashCommands(message.commands);
              await this.client.sessionUpdate({
                sessionId,
                update: {
                  sessionUpdate: "available_commands_update",
                  availableCommands: available,
                },
              });
              this.updateBreakdownCategory(
                "skills",
                estimateSkillsTokens(available),
              );
              break;
            }
            if (message.subtype === "local_command_output") {
              await ensureActiveTurn();
            }
            if (message.subtype === "status") {
              // The SDK signals manual `/compact` completion with a status
              // message carrying `compact_result`, not the `compact_boundary`
              // message (which only fires when there's content to compact).
              // Gate the user-facing outcome on `compactionInProgress` to
              // dedupe the duplicate terminal status the SDK emits for failed
              // compactions.
              if (message.status === "compacting") {
                compactionInProgress = true;
                // Fall through to handleSystemMessage so the COMPACTING
                // extNotification still fires.
              } else if (
                message.compact_result === "success" &&
                compactionInProgress
              ) {
                compactionInProgress = false;
                await this.client.sessionUpdate({
                  sessionId,
                  update: {
                    sessionUpdate: "agent_message_chunk",
                    content: {
                      type: "text",
                      text: "\n\nCompacting completed.",
                    },
                  },
                });
                // Clear the "Compacting…" spinner. On success a `compact_boundary`
                // usually also clears it, but a no-op success carries none, so
                // signal completion explicitly.
                await this.client.extNotification(
                  POSTHOG_NOTIFICATIONS.STATUS,
                  {
                    sessionId,
                    status: "compacting",
                    isComplete: true,
                  },
                );
                break;
              } else if (
                message.compact_result === "failed" &&
                compactionInProgress
              ) {
                compactionInProgress = false;
                // A failed compaction never emits a `compact_boundary`, so emit a
                // structured failure status: the renderer clears the "Compacting…"
                // spinner and reports the outcome as its own status row (a separator
                // marker in the new thread), not as assistant prose.
                await this.client.extNotification(
                  POSTHOG_NOTIFICATIONS.STATUS,
                  {
                    sessionId,
                    status: "compacting_failed",
                    error: message.compact_error ?? undefined,
                  },
                );
                break;
              }
            }
            if (
              message.subtype === "session_state_changed" &&
              (message as Record<string, unknown>).state === "idle"
            ) {
              if (session.activeTurn) {
                // Only a cancelled turn settles at idle; its result was
                // dropped at the `session.cancelled` guard.
                if (session.cancelled) {
                  settleActive(this.cancelledResponse());
                }
                await this.maybeUpdateSessionTitle(sessionId, session);
                break;
              }
              await this.maybeUpdateSessionTitle(sessionId, session);
              // An unknown command the SDK consumed silently never echoes;
              // known plugin/skill commands echo late (race, not unsupported).
              const head = session.turnQueue.find((t) => !t.settled);
              if (
                head?.commandName &&
                session.pendingOrphanResults === 0 &&
                session.knownSlashCommands?.has(head.commandName.slice(1)) !==
                  true
              ) {
                const cmd = head.commandName;
                this.logger.warn(
                  "Slash command produced no output; treating as unsupported",
                  { sessionId, command: cmd },
                );
                await this.client.sessionUpdate({
                  sessionId,
                  update: {
                    sessionUpdate: "agent_message_chunk",
                    content: {
                      type: "text",
                      text: `Unsupported slash command: \`${cmd}\`. PostHog does not implement this command.`,
                    },
                  },
                });
                head.settled = true;
                session.turnQueue = session.turnQueue.filter((t) => t !== head);
                head.resolve({ stopReason: "end_turn" });
                break;
              }
              this.logger.debug("Idle without an active turn", {
                sessionId,
                queuedTurns: session.turnQueue.length,
                command: head?.commandName,
              });
              break;
            }
            await handleSystemMessage(message, context);
            break;

          case "result": {
            // Task-notification followups are background work: they must not
            // touch the user-turn lifecycle, but their cost is still reported.
            const isTaskNotification =
              (message as { origin?: { kind?: string } }).origin?.kind ===
              "task-notification";

            if (!isTaskNotification) {
              await this.syncFastModeState(
                (message as { fast_mode_state?: FastModeState })
                  .fast_mode_state,
              );
            }

            // Promote before accumulating usage: activation resets the
            // accumulator.
            if (!isTaskNotification) {
              await ensureActiveTurn();
            }

            // A cancelled turn settles at idle (or the backstop) instead.
            if (session.cancelled) {
              break;
            }

            if (!isTaskNotification) {
              // Accumulate usage from this result (guard against null from SDK)
              session.accumulatedUsage.inputTokens +=
                message.usage.input_tokens ?? 0;
              session.accumulatedUsage.outputTokens +=
                message.usage.output_tokens ?? 0;
              session.accumulatedUsage.cachedReadTokens +=
                message.usage.cache_read_input_tokens ?? 0;
              session.accumulatedUsage.cachedWriteTokens +=
                message.usage.cache_creation_input_tokens ?? 0;
            }

            // SDK can underreport context window (e.g. 200k for 1M models).
            // Use SDK value only if it's larger than what gateway reported.
            const contextWindows = Object.values(message.modelUsage).map(
              (m) => m.contextWindow,
            );
            if (contextWindows.length > 0) {
              const sdkContextWindow = Math.min(...contextWindows);
              if (sdkContextWindow > windowSize()) {
                session.lastContextWindowSize = sdkContextWindow;
              }
            }

            session.contextSize = windowSize();
            if (lastAssistantTotalUsage !== null) {
              session.contextUsed = lastAssistantTotalUsage;
            }

            // Send usage_update notification
            if (lastAssistantTotalUsage !== null) {
              await this.client.sessionUpdate({
                sessionId,
                update: {
                  sessionUpdate: "usage_update",
                  used: lastAssistantTotalUsage,
                  size: windowSize(),
                  cost: {
                    amount: message.total_cost_usd,
                    currency: "USD",
                  },
                },
              });
            }

            // `result.usage` is cumulative across the agentic loop; the
            // outermost-model stream snapshot is what's actually resident.
            const breakdownInputTokens =
              lastStreamUsage.input_tokens +
              lastStreamUsage.cache_read_input_tokens +
              lastStreamUsage.cache_creation_input_tokens;
            await this.client.extNotification(
              POSTHOG_NOTIFICATIONS.USAGE_UPDATE,
              {
                sessionId,
                used: {
                  inputTokens: message.usage.input_tokens,
                  outputTokens: message.usage.output_tokens,
                  cachedReadTokens: message.usage.cache_read_input_tokens,
                  cachedWriteTokens: message.usage.cache_creation_input_tokens,
                },
                cost: message.total_cost_usd,
                breakdown: buildBreakdown(
                  session.contextBreakdownBaseline ?? emptyBaseline(),
                  breakdownInputTokens,
                ),
              },
            );

            if (
              !isTaskNotification &&
              session.activeTurn &&
              session.activeTurn.pendingSteerUuids.size > 0
            ) {
              this.logger.debug(
                "Deferring turn completion until pending steers are consumed",
                {
                  sessionId,
                  pendingSteers: session.activeTurn.pendingSteerUuids.size,
                },
              );
              break;
            }

            if (
              (message as { stop_reason?: string }).stop_reason === "refusal"
            ) {
              // The API's stop_details.explanation is integrator-facing prose,
              // so surface the refusal as a structured status row rather than
              // assistant text.
              await this.client.extNotification(POSTHOG_NOTIFICATIONS.STATUS, {
                sessionId,
                status: "refusal",
                ...(lastRefusalExplanation && {
                  explanation: lastRefusalExplanation,
                }),
                ...(lastRefusalCategory && { category: lastRefusalCategory }),
              });
              if (isTaskNotification) {
                // Background work never activates a turn, so there is no
                // settle path to broadcast completion — send it directly so
                // the UI still closes this reply out as its own turn.
                await this.client.extNotification(
                  POSTHOG_NOTIFICATIONS.BACKGROUND_TURN_COMPLETE,
                  { sessionId, stopReason: "refusal" },
                );
              } else {
                stopReason = "refusal";
                settleActive({ stopReason: "refusal", usage: sessionUsage() });
              }
              break;
            }

            const result = handleResultMessage(message);
            if (result.error) {
              if (!isTaskNotification) {
                failActive(result.error);
              }
              break;
            }

            // Deliver structured output from SDK's native outputFormat
            if (
              message.subtype === "success" &&
              message.structured_output != null &&
              this.options?.onStructuredOutput
            ) {
              await this.options.onStructuredOutput(
                message.structured_output as Record<string, unknown>,
              );
            }

            // For local-only commands, forward the result text to the client
            if (
              session.activeTurn?.isLocalOnlyCommand &&
              !isTaskNotification &&
              message.subtype === "success" &&
              message.result
            ) {
              await this.client.sessionUpdate({
                sessionId,
                update: {
                  sessionUpdate: "agent_message_chunk",
                  content: { type: "text", text: message.result },
                },
              });
            }

            // Settle at the terminal result rather than the trailing idle,
            // which can lag behind background work.
            if (isTaskNotification) {
              // Background work never activates a turn, so there is no
              // settle path to broadcast completion — send it directly so
              // the UI still closes this reply out as its own turn instead
              // of merging the next one into it.
              await this.client.extNotification(
                POSTHOG_NOTIFICATIONS.BACKGROUND_TURN_COMPLETE,
                { sessionId, stopReason: result.stopReason ?? "end_turn" },
              );
            } else {
              stopReason = result.stopReason ?? "end_turn";
              settleActive({ stopReason, usage: sessionUsage() });
            }
            break;
          }

          case "stream_event": {
            if (
              message.parent_tool_use_id === null &&
              (message.event.type === "message_start" ||
                message.event.type === "message_delta")
            ) {
              if (message.event.type === "message_start") {
                const u = message.event.message.usage;
                lastStreamUsage = {
                  input_tokens: u.input_tokens ?? 0,
                  output_tokens: u.output_tokens ?? 0,
                  cache_read_input_tokens: u.cache_read_input_tokens ?? 0,
                  cache_creation_input_tokens:
                    u.cache_creation_input_tokens ?? 0,
                };
              } else {
                const u = message.event.usage;
                lastStreamUsage = {
                  input_tokens: u.input_tokens ?? lastStreamUsage.input_tokens,
                  output_tokens: u.output_tokens,
                  cache_read_input_tokens:
                    u.cache_read_input_tokens ??
                    lastStreamUsage.cache_read_input_tokens,
                  cache_creation_input_tokens:
                    u.cache_creation_input_tokens ??
                    lastStreamUsage.cache_creation_input_tokens,
                };
              }

              const nextTotal =
                lastStreamUsage.input_tokens +
                lastStreamUsage.output_tokens +
                lastStreamUsage.cache_read_input_tokens +
                lastStreamUsage.cache_creation_input_tokens;

              if (recordContextUsage(nextTotal)) {
                await this.client.sessionUpdate({
                  sessionId,
                  update: {
                    sessionUpdate: "usage_update",
                    used: nextTotal,
                    size: windowSize(),
                  },
                });
              }
            }
            await handleStreamEvent(message, context);
            break;
          }

          case "user":
          case "assistant": {
            // A user echo promotes its queued turn (handing off any still-
            // active one first), then drops from the feed. Runs before the
            // cancelled guard so a turn enqueued after a cancel still starts.
            if (message.type === "user" && "uuid" in message && message.uuid) {
              if (session.activeTurn?.pendingSteerUuids.delete(message.uuid)) {
                break;
              }
              const queued = session.turnQueue.find(
                (t) => t.promptUuid === message.uuid && !t.settled,
              );
              if (queued) {
                // A turn promoted early by its result must not have its
                // usage reset by its own echo.
                if (session.activeTurn !== queued) {
                  if (session.activeTurn) {
                    settleActive(
                      session.cancelled
                        ? this.cancelledResponse()
                        : { stopReason: "end_turn", usage: sessionUsage() },
                    );
                  }
                  await activateTurn(queued);
                }
                break;
              }
              if (
                "isReplay" in message &&
                (message as Record<string, unknown>).isReplay
              ) {
                break;
              }
            }

            if (session.cancelled) {
              break;
            }

            // Skip replayed messages that aren't queued prompts
            if (
              "isReplay" in message &&
              (message as Record<string, unknown>).isReplay
            ) {
              break;
            }

            if (message.type === "assistant") {
              const inner = message.message as unknown as {
                stop_reason?: string | null;
                stop_details?: {
                  category?: string | null;
                  explanation?: string | null;
                } | null;
              };
              if (inner.stop_reason === "refusal") {
                lastRefusalExplanation =
                  inner.stop_details?.explanation ?? null;
                lastRefusalCategory = inner.stop_details?.category ?? null;
              }
            }

            // Store latest assistant usage (excluding subagents)
            // Sum all token types as a proxy for post-turn context occupancy:
            // current turn's output will become next turn's input.
            // Note: per the Anthropic API, input_tokens excludes cache tokens —
            // cache_read and cache_creation are reported separately, so summing
            // all four fields is not double-counting.
            if (
              "usage" in message.message &&
              message.parent_tool_use_id === null
            ) {
              const usage = (
                message.message as unknown as Record<string, unknown>
              ).usage as {
                input_tokens: number | null;
                output_tokens: number | null;
                cache_read_input_tokens: number | null;
                cache_creation_input_tokens: number | null;
              };
              const nextTotal =
                (usage.input_tokens ?? 0) +
                (usage.output_tokens ?? 0) +
                (usage.cache_read_input_tokens ?? 0) +
                (usage.cache_creation_input_tokens ?? 0);

              if (recordContextUsage(nextTotal)) {
                await this.client.sessionUpdate({
                  sessionId,
                  update: {
                    sessionUpdate: "usage_update",
                    used: nextTotal,
                    size: windowSize(),
                    cost: null,
                  },
                });
              }
            }

            const result = await handleUserAssistantMessage(message, context);
            if (result.error) {
              failActive(result.error);
              break;
            }
            if (result.shouldStop) {
              settleActive({ stopReason: "end_turn" });
            }
            break;
          }

          case "tool_progress": {
            await this.client.sessionUpdate({
              sessionId,
              update: {
                sessionUpdate: "tool_call_update",
                toolCallId: message.tool_use_id,
                status: "in_progress",
                _meta: {
                  claudeCode: {
                    toolName: message.tool_name,
                    toolResponse: {
                      elapsedTimeSeconds: message.elapsed_time_seconds,
                    },
                  },
                } satisfies ToolUpdateMeta,
              },
            });
            break;
          }
          case "rate_limit_event": {
            if (lastAssistantTotalUsage !== null) {
              await this.client.sessionUpdate({
                sessionId,
                update: {
                  sessionUpdate: "usage_update",
                  used: lastAssistantTotalUsage,
                  size: windowSize(),
                  _meta: { "_claude/rateLimit": message.rate_limit_info },
                },
              });
            }
            break;
          }
          case "auth_status":
          case "tool_use_summary":
          case "prompt_suggestion":
            break;

          default:
            unreachable(message as never, this.logger);
            break;
        }
      }
    } catch (error) {
      // Only stream-level errors reach here; turn-level failures were
      // rejected inline via failActive.
      if (refreshed()) {
        this.logger.debug("Consumer for a refreshed query exiting on error", {
          sessionId,
          error: error instanceof Error ? error.message : String(error),
        });
        return;
      }
      const msg = error instanceof Error ? error.message : String(error);
      const processDied =
        error instanceof Error &&
        (msg.includes("ProcessTransport") ||
          msg.includes("terminated process") ||
          msg.includes("process exited with") ||
          msg.includes("process terminated by signal") ||
          msg.includes("Failed to write to process stdin"));
      if (processDied) {
        this.logger.error(`Process died: ${msg}`, {
          sessionId: this.sessionId,
        });
        failAllTurns(
          RequestError.internalError(
            { details: msg },
            "The Claude Agent process exited unexpectedly. Please start a new session.",
          ),
        );
      } else {
        this.logger.error("Query stream error", { sessionId, error: msg });
        failAllTurns(error);
      }
      this.closeQueryStream(session);
    }
  }

  // Called by BaseAcpAgent#cancel() to interrupt the session
  protected async interrupt(): Promise<void> {
    const session = this.session;
    if (session.queryClosed) {
      return;
    }
    session.cancelled = true;

    // Settle not-yet-echoed turns immediately; the SDK still runs their
    // pushed messages, so count the echo-less results they owe as orphans.
    for (const turn of [...session.turnQueue]) {
      if (turn === session.activeTurn || turn.settled) {
        continue;
      }
      turn.settled = true;
      session.turnQueue = session.turnQueue.filter((t) => t !== turn);
      session.pendingOrphanResults += 1;
      turn.resolve(this.cancelledResponse());
    }

    // Backstop for an SDK that never yields after interrupt() (issue #680).
    if (
      session.activeTurn &&
      session.cancelController &&
      !session.cancelController.signal.aborted &&
      !session.forceCancelTimer
    ) {
      const cancelController = session.cancelController;
      session.forceCancelTimer = setTimeout(() => {
        this.logger.error(
          `Session ${this.sessionId}: cancel floor elapsed without the SDK yielding; forcing "cancelled". The underlying query may still be wedged — a new session may be required.`,
        );
        cancelController.abort();
      }, this.forceCancelGraceMs);
    }

    await session.query.interrupt();
  }

  /**
   * Refresh the session between turns. Currently the only refreshable field
   * is `mcpServers` — a resume-with-new-options reinit that bakes the servers
   * into query() options (preserving conversation history via resume).
   *
   * This is an `extMethod` (request/response), not `extNotification`, so the
   * caller can await completion before sending the next prompt. The sandbox
   * agent-server uses this on pre-prompt TTL checks.
   *
   * Why resume+rebuild instead of query.setMcpServers()?
   * setMcpServers() does NOT always overwrite servers installed by local/plugin
   * config — it can non-deterministically surface either the config-provided
   * server or the plugin-installed one. In the sandbox, repos may have Claude
   * plugins with their own MCPs, and we want the CLI-supplied set to fully win.
   * Passing mcpServers via query() options (as a "managed"/static set) has that
   * overwrite guarantee, so we tear down the current Query and construct a new
   * one with resume.
   *
   * Caller contract: only call REFRESH_SESSION between turns (no prompt in flight).
   */
  async extMethod(
    method: string,
    params: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    if (!isMethod(method, POSTHOG_METHODS.REFRESH_SESSION)) {
      throw RequestError.methodNotFound(method);
    }

    // Trust boundary: refresh is only safe when the caller is trusted infra
    // (e.g. the sandbox agent-server). Do not route this method from
    // untrusted clients — parseMcpServers does no URL/command validation.
    if (params.mcpServers === undefined) {
      throw new RequestError(
        -32602,
        "refresh_session requires at least one refreshable field (e.g. mcpServers)",
      );
    }
    if (!Array.isArray(params.mcpServers)) {
      throw new RequestError(
        -32602,
        "refresh_session: mcpServers must be an array",
      );
    }

    const mcpServers = parseMcpServers(
      params as Pick<NewSessionRequest, "mcpServers">,
      this.logger,
    );
    await this.refreshSession(mcpServers);
    return { refreshed: true };
  }

  private async refreshSession(
    mcpServers: Record<string, McpServerConfig>,
  ): Promise<void> {
    const prev = this.session;
    if (prev.activeTurn !== null || prev.turnQueue.length > 0) {
      throw new RequestError(
        -32002,
        "Cannot refresh session while a prompt turn is in flight",
      );
    }
    if (prev.modelId && !supportsMcpInjection(prev.modelId)) {
      throw new RequestError(
        -32002,
        `Model ${prev.modelId} does not support MCP injection; cannot refresh`,
      );
    }

    this.logger.info("Refreshing session with fresh MCP servers", {
      serverCount: Object.keys(mcpServers).length,
      sessionId: this.sessionId,
    });

    // Retire the old consumer: the generation bump makes it exit quietly.
    prev.queryGeneration += 1;
    const oldConsumer = prev.consumer;
    prev.consumer = undefined;
    prev.cancelController?.abort();
    prev.cancelController = undefined;

    // Abort FIRST so any stuck in-flight HTTP request unblocks — otherwise
    // interrupt() can deadlock waiting on an API call that never returns.
    // We allocate a fresh controller for the new Query below so aborting
    // the old one doesn't poison it.
    prev.abortController.abort();
    try {
      await prev.query.interrupt();
    } catch (error) {
      this.logger.debug("Ignoring interrupt error during session refresh", {
        sessionId: this.sessionId,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    prev.input.end();
    if (oldConsumer) {
      // Bounded so a wedged old query can't block the refresh.
      await withTimeout(oldConsumer, 5_000);
    }

    // Reuse every option from the running session; swap mcpServers, re-root
    // identity on `resume` instead of `sessionId`, and give the new Query a
    // fresh AbortController.
    const newAbortController = new AbortController();
    const { sessionId: _drop, ...rest } = prev.queryOptions;

    // Rebuild the in-process ("sdk") server fresh; reusing the prior instance
    // throws "Already connected to a transport" and drops the signed-commit tools.
    const freshInProcess = prev.buildInProcessMcpServers();
    if (Object.keys(freshInProcess).length > 0) {
      this.logger.info("Rebuilt in-process MCP servers on refresh", {
        sessionId: this.sessionId,
        servers: Object.keys(freshInProcess),
      });
    }

    const newOptions: Options = {
      ...rest,
      mcpServers: { ...mcpServers, ...freshInProcess },
      resume: this.sessionId,
      forkSession: false,
      abortController: newAbortController,
      // `rest.model` is the creation-time value; the user may have switched
      // models since, so re-root the new Query on the live session model.
      ...(prev.modelId && { model: toSdkModelId(prev.modelId) }),
    };

    const newInput = new Pushable<SDKUserMessage>();
    const newQuery = query({ prompt: newInput, options: newOptions });

    prev.query = newQuery;
    prev.input = newInput;
    prev.queryOptions = newOptions;
    prev.abortController = newAbortController;

    const result = await withTimeout(
      newQuery.initializationResult(),
      SESSION_VALIDATION_TIMEOUT_MS,
    );
    if (result.result === "timeout") {
      this.terminateQuery(newQuery, newAbortController);
      throw new RequestError(
        -32603,
        `Session refresh timed out after ${SESSION_VALIDATION_TIMEOUT_MS}ms`,
        { sessionId: this.sessionId },
      );
    }

    this.refreshMcpMetadata(newQuery);
  }

  /**
   * Best-effort self-heal: if the in-process signed-commit server is enabled but
   * the live Query reports it disconnected, rebuild a fresh instance and
   * reconnect via setMcpServers. Returns whether the tooling is usable after.
   */
  private async ensureLocalToolsConnected(trigger: string): Promise<boolean> {
    const names = this.session.localToolsServerNames;
    if (names.length === 0) {
      return true;
    }

    const status = await withTimeout(
      this.session.query.mcpServerStatus(),
      MCP_STATUS_TIMEOUT_MS,
    ).catch((error) => {
      this.logger.debug("ensureLocalToolsConnected: status check failed", {
        trigger,
        error: error instanceof Error ? error.message : String(error),
      });
      return { result: "timeout" as const };
    });
    // A slow or failed status RPC must not block the turn; assume healthy.
    if (status.result !== "success") {
      return true;
    }

    const allConnected = names.every((name) =>
      status.value.some((s) => s.name === name && s.status === "connected"),
    );
    if (allConnected) {
      return true;
    }

    const logCtx = { trigger, sessionId: this.sessionId, servers: names };
    this.logger.warn(
      "Signed-commit MCP server unhealthy; reconnecting",
      logCtx,
    );

    try {
      const next = {
        ...externalMcpServers(this.session.queryOptions.mcpServers),
        ...this.session.buildInProcessMcpServers(),
      };
      await this.session.query.setMcpServers(next);
      this.session.queryOptions.mcpServers = next;
      this.refreshMcpMetadata(this.session.query);
      this.logger.info("Reconnected signed-commit MCP server", logCtx);
      return true;
    } catch (error) {
      this.logger.error("Failed to reconnect signed-commit MCP server", {
        ...logCtx,
        error: error instanceof Error ? error.message : String(error),
      });
      return false;
    }
  }

  /** Clear stale MCP tool metadata, then re-fetch it for the new server set. */
  private refreshMcpMetadata(q: Query): void {
    clearMcpToolMetadataCache();
    this.deferBackgroundFetches(q);
  }

  async setSessionMode(
    params: SetSessionModeRequest,
  ): Promise<SetSessionModeResponse> {
    await this.applySessionMode(params.modeId);
    await this.updateConfigOption("mode", params.modeId);
    return {};
  }

  async setSessionConfigOption(
    params: SetSessionConfigOptionRequest,
  ): Promise<SetSessionConfigOptionResponse> {
    const option = this.session.configOptions.find(
      (o) => o.id === params.configId,
    );
    if (!option) {
      throw new Error(`Unknown config option: ${params.configId}`);
    }

    if (typeof params.value !== "string") {
      throw new Error(
        `Invalid value type for config option ${params.configId}`,
      );
    }

    const allValues: { value: string; name?: string; description?: string }[] =
      "options" in option && Array.isArray(option.options)
        ? (option.options as Array<Record<string, unknown>>).flatMap((o) =>
            "options" in o && Array.isArray(o.options)
              ? (o.options as {
                  value: string;
                  name?: string;
                  description?: string;
                }[])
              : [o as { value: string; name?: string; description?: string }],
          )
        : [];
    let validValue = allValues.find((o) => o.value === params.value);

    // For model options, fall back to alias resolution when exact match fails.
    // This lets callers use human-friendly aliases like "opus" or "sonnet"
    // instead of full model IDs like "claude-opus-4-8".
    if (!validValue && params.configId === "model") {
      const resolved = resolveModelPreference(params.value, allValues);
      if (resolved) {
        validValue = allValues.find((o) => o.value === resolved);
      }
    }

    if (!validValue) {
      throw new Error(
        `Invalid value for config option ${params.configId}: ${params.value}`,
      );
    }

    // Use the canonical option value so downstream code always receives the
    // model ID rather than the caller-supplied alias.
    const resolvedValue = validValue.value;

    if (params.configId === "mode") {
      await this.applySessionMode(resolvedValue);
      await this.client.sessionUpdate({
        sessionId: this.sessionId,
        update: {
          sessionUpdate: "current_mode_update",
          currentModeId: resolvedValue,
        },
      });
    } else if (params.configId === "model") {
      const sdkModelId = toSdkModelId(resolvedValue);
      await this.session.query.setModel(sdkModelId);
      this.session.modelId = resolvedValue;
      this.session.lastContextWindowSize =
        this.getContextWindowForModel(resolvedValue);
      this.rebuildEffortConfigOption(resolvedValue);
      this.rebuildFastModeConfigOption(resolvedValue);
    } else if (params.configId === "effort") {
      const newEffort = resolvedValue as EffortLevel;
      this.session.effort = newEffort;
      this.session.queryOptions.effort = newEffort;
      await this.session.query.applyFlagSettings({
        // @ts-expect-error SDK Settings.effortLevel omits "max" but runtime accepts it
        effortLevel: newEffort,
      });
    } else if (params.configId === "fast") {
      // SDK flag first: a rejected control request leaves state untouched.
      const enabled = resolvedValue === "on";
      await this.session.query.applyFlagSettings({ fastMode: enabled });
      this.session.fastModeEnabled = enabled;
    }

    this.session.configOptions = this.session.configOptions.map((o) =>
      o.id === params.configId && typeof o.currentValue === "string"
        ? { ...o, currentValue: resolvedValue }
        : o,
    );

    await this.client.sessionUpdate({
      sessionId: this.sessionId,
      update: {
        sessionUpdate: "config_option_update",
        configOptions: this.session.configOptions,
      },
    });

    return { configOptions: this.session.configOptions };
  }

  private async updateConfigOption(
    configId: string,
    value: string,
  ): Promise<void> {
    this.session.configOptions = this.session.configOptions.map((o) =>
      o.id === configId && typeof o.currentValue === "string"
        ? { ...o, currentValue: value }
        : o,
    );

    await this.client.sessionUpdate({
      sessionId: this.sessionId,
      update: {
        sessionUpdate: "config_option_update",
        configOptions: this.session.configOptions,
      },
    });

    // Notify the agent-server so its cached permissionMode stays in sync.
    // Without this, cloud sessions that change mode via plan approval or
    // setSessionMode use a stale mode for relay decisions.
    if (configId === "mode") {
      await this.client.sessionUpdate({
        sessionId: this.sessionId,
        update: {
          sessionUpdate: "current_mode_update",
          currentModeId: value,
        },
      });
    }
  }

  private async applySessionMode(modeId: string): Promise<void> {
    if (!CODE_EXECUTION_MODES.includes(modeId as CodeExecutionMode)) {
      throw new Error("Invalid Mode");
    }
    const previousMode = this.session.permissionMode;
    this.session.permissionMode = modeId as CodeExecutionMode;
    if (modeId === "plan" && previousMode !== "plan") {
      this.session.modeBeforePlan = previousMode;
    }
    try {
      await this.session.query.setPermissionMode(
        toSdkPermissionMode(modeId as CodeExecutionMode),
      );
    } catch (error) {
      this.session.permissionMode = previousMode;
      if (error instanceof Error) {
        if (!error.message) {
          error.message = "Invalid Mode";
        }
        throw error;
      }
      throw new Error("Invalid Mode");
    }
  }

  private async validateCwd(cwd: string): Promise<void> {
    if (!path.isAbsolute(cwd)) {
      throw RequestError.invalidParams(
        { cwd },
        `\`cwd\` must be an absolute path, but received: ${cwd}`,
      );
    }

    let stats: fs.Stats;
    try {
      stats = await fs.promises.stat(cwd);
    } catch {
      throw RequestError.invalidParams(
        { cwd },
        `\`cwd\` does not exist on the machine running the agent: ${cwd}`,
      );
    }

    if (!stats.isDirectory()) {
      throw RequestError.invalidParams(
        { cwd },
        `\`cwd\` is not a directory: ${cwd}`,
      );
    }
  }

  /**
   * Without this, a timed-out session leaks an orphaned `claude` process that
   * the retry loop then multiplies. Aborting the controller kills the
   * subprocess via the spawn signal; closing the query stops further reads.
   */
  private terminateQuery(sdkQuery: Query, controller: AbortController): void {
    controller.abort();
    try {
      sdkQuery.close();
    } catch {
      // Query may already be closed.
    }
  }

  // Backs the `finish` local tool: marks the task run terminal so the Temporal
  // workflow tears the sandbox down. Only wired when we have both the run
  // identifiers and a PostHog API config, i.e. a real cloud run.
  private buildRequestFinish(
    taskId: string | undefined,
    taskRunId: string | undefined,
  ): LocalToolCtx["requestFinish"] {
    const config = this.options?.posthogApiConfig;
    if (!config || !taskId || !taskRunId) {
      return undefined;
    }
    return async (status, message) => {
      try {
        await new PostHogAPIClient(config).updateTaskRun(taskId, taskRunId, {
          status,
          ...(status === "failed" && message ? { error_message: message } : {}),
        });
      } catch (error) {
        this.logger.error("finish tool failed to mark run terminal", error);
        throw error;
      }
    };
  }

  private async createSession(
    params: {
      cwd: string;
      mcpServers: NewSessionRequest["mcpServers"];
      additionalDirectories?: NewSessionRequest["additionalDirectories"];
      _meta?: unknown;
    },
    creationOpts: {
      resume?: string;
      forkSession?: boolean;
      skipBackgroundFetches?: boolean;
    } = {},
  ): Promise<NewSessionResponse> {
    const { cwd } = params;
    const { resume, forkSession } = creationOpts;

    await this.validateCwd(cwd);

    const isResume = !!resume;

    const meta = params._meta as NewSessionMeta | undefined;
    const taskId = resolveTaskId(meta);
    // Gate signed-commit wiring on cloud-run detection so the desktop (which
    // signs via CommitSaga) is untouched.
    const cloudRun = isCloudRun(meta);
    const effort = meta?.claudeCode?.options?.effort as EffortLevel | undefined;

    // We want to create a new session id unless it is resume,
    // but not resume + forkSession.
    let sessionId: string;
    if (forkSession) {
      sessionId = uuidv7();
    } else if (isResume) {
      sessionId = resume;
    } else {
      sessionId = uuidv7();
    }

    const input = new Pushable<SDKUserMessage>();

    const settingsManager = new SettingsManager(cwd);
    await settingsManager.initialize();

    const earlyModelId =
      settingsManager.getSettings().model || meta?.model || "";

    // Register the in-process general local-tools MCP server. Tools self-gate
    // via the registry (e.g. signed-commit is cloud-only and needs a GH token),
    // so adding a tool needs no change here. In cloud runs `git commit`/`git
    // push` are blocked by the PreToolUse guard (and the sandbox git shim), so
    // the agent commits via the signed-commit tool instead.
    //
    // A closure so refresh/self-heal can rebuild a fresh instance (reusing one
    // throws "Already connected to a transport"). Capture only the fields it
    // needs so the session doesn't pin the whole meta object.
    const baseBranch = meta?.baseBranch;
    const environment = meta?.environment;
    const spokenNarration = resolveSpokenNarration(meta);
    const requestFinish = this.buildRequestFinish(taskId, meta?.taskRunId);
    const buildInProcessMcpServers = (): Record<
      string,
      McpSdkServerConfigWithInstance
    > => {
      const server = createLocalToolsMcpServer(
        {
          cwd,
          token: resolveGithubToken(),
          taskId,
          taskRunId: meta?.taskRunId,
          baseBranch,
          requestFinish,
        },
        {
          environment,
          spokenNarration,
          background: meta?.mode === "background",
        },
      );
      return server ? { [LOCAL_TOOLS_MCP_NAME]: server } : {};
    };

    const initialInProcess = buildInProcessMcpServers();
    const localToolsServerNames = Object.keys(initialInProcess);
    if (localToolsServerNames.length === 0 && cloudRun) {
      this.logger.warn(
        "Cloud run registered no local tools (missing GH_TOKEN/GITHUB_TOKEN?); signed commits unavailable",
      );
    }

    const mcpServers: Record<string, McpServerConfig> = {
      ...(supportsMcpInjection(earlyModelId)
        ? parseMcpServers(params, this.logger)
        : {}),
      ...initialInProcess,
    };

    const systemPrompt = buildSystemPrompt(meta?.systemPrompt, {
      spokenNarration,
    });

    if (meta?.mcpToolApprovals) {
      setMcpToolApprovalStates(meta.mcpToolApprovals);
    }

    // Configure structured output via SDK's native outputFormat
    const outputFormat =
      meta?.jsonSchema && this.options?.onStructuredOutput
        ? { type: "json_schema" as const, schema: meta.jsonSchema }
        : undefined;

    this.logger.debug(isResume ? "Resuming session" : "Creating new session", {
      sessionId,
      taskId,
      taskRunId: meta?.taskRunId,
      cwd,
    });

    const permissionMode: CodeExecutionMode =
      meta?.permissionMode &&
      CODE_EXECUTION_MODES.includes(meta.permissionMode as CodeExecutionMode)
        ? (meta.permissionMode as CodeExecutionMode)
        : "default";
    const posthogExecPermissionRegex = resolvePostHogExecPermissionRegex(
      meta?.posthogExecPermissionRegex,
      (message) =>
        this.logger.warn(
          "Invalid posthogExecPermissionRegex in session metadata; using default",
          { message },
        ),
    );

    const taskState: TaskState = new Map();
    const options = buildSessionOptions({
      cwd,
      mcpServers,
      permissionMode,
      posthogExecPermissionRegex,
      canUseTool: this.createCanUseTool(sessionId, meta?.allowedDomains),
      logger: this.logger,
      systemPrompt,
      userProvidedOptions: meta?.claudeCode?.options,
      sessionId,
      isResume,
      forkSession,
      additionalDirectories: [
        ...(meta?.claudeCode?.options?.additionalDirectories ?? []),
        // Prefer the official ACP `additionalDirectories` field. Fall back
        // to the legacy `_meta.additionalRoots` extension for clients that
        // haven't been updated yet.
        ...(params.additionalDirectories ?? meta?.additionalRoots ?? []),
      ],
      disableBuiltInTools: meta?.disableBuiltInTools,
      outputFormat,
      settingsManager,
      onModeChange: this.createOnModeChange(),
      onPostHogResourceUsed: this.createOnPostHogResourceUsed(),
      onProcessSpawned: this.options?.onProcessSpawned,
      onProcessExited: this.options?.onProcessExited,
      effort,
      enrichmentDeps: this.enrichment?.deps,
      enrichedReadCache: this.enrichedReadCache,
      cloudMode: cloudRun,
      onEnsureLocalToolsConnected: () =>
        this.ensureLocalToolsConnected("guard-hook"),
      taskState,
      gatewayEnv: this.options?.gatewayEnv,
      onTaskStateChange: async () => {
        await this.client.sessionUpdate({
          sessionId,
          update: {
            sessionUpdate: "plan",
            entries: taskStateToPlanEntries(taskState),
          },
        });
      },
    });

    // Use the same abort controller that buildSessionOptions gave to the query
    const abortController = options.abortController as AbortController;

    const q = query({ prompt: input, options });

    const session: Session = {
      query: q,
      queryOptions: options,
      buildInProcessMcpServers,
      localToolsServerNames,
      input,
      cancelled: false,
      settingsManager,
      permissionMode,
      cloudMode: cloudRun,
      posthogExecPermissionRegex,
      abortController,
      accumulatedUsage: {
        inputTokens: 0,
        outputTokens: 0,
        cachedReadTokens: 0,
        cachedWriteTokens: 0,
      },
      sessionResources: new Set(),
      effort,
      configOptions: [],
      turnQueue: [],
      activeTurn: null,
      pendingOrphanResults: 0,
      queryGeneration: 0,
      fastModeEnabled: false,
      emitRawSDKMessages: meta?.claudeCode?.emitRawSDKMessages ?? false,
      contextBreakdownBaseline: {
        ...emptyBaseline(),
        systemPrompt: estimateSystemPrompt(systemPrompt),
        rules: estimateRulesTokens(readClaudeMdQuietly(cwd, this.logger)),
      },
      taskState,

      // Custom properties
      cwd,
      notificationHistory: [],
      taskRunId: meta?.taskRunId,
    };
    // A replaced session's consumer never reaches closeQueryStream.
    this.emittedToolCalls.clear();
    this.session = session;
    this.sessionId = sessionId;

    if (isResume) {
      // Resume must block on initialization to validate the session is still alive.
      // For stale sessions this throws (e.g. "No conversation found").
      try {
        const result = await withTimeout(
          q.initializationResult(),
          SESSION_VALIDATION_TIMEOUT_MS,
        );
        if (result.result === "timeout") {
          throw new RequestError(
            -32603,
            `Session ${forkSession ? "fork" : "resumption"} timed out after ${SESSION_VALIDATION_TIMEOUT_MS}ms`,
            { sessionId, taskId, taskRunId: meta?.taskRunId },
          );
        }
        session.knownSlashCommands = collectKnownSlashCommands(
          result.value.commands,
        );
        session.fastModeEnabled = fastModeStateEnabled(
          result.value.fast_mode_state,
        );
      } catch (err) {
        settingsManager.dispose();
        this.terminateQuery(q, abortController);
        if (
          err instanceof Error &&
          err.message === "Query closed before response received"
        ) {
          throw RequestError.resourceNotFound(sessionId);
        }
        this.logger.error(
          forkSession ? "Session fork failed" : "Session resumption failed",
          {
            sessionId,
            taskId,
            taskRunId: meta?.taskRunId,
            errorDetail: serializeError(err),
          },
        );
        throw err;
      }
    }

    // Kick off SDK initialization for new sessions so it runs concurrently
    // with the model config fetch below (the gateway REST call is independent).
    const initStartedAt = Date.now();
    const initPromise = !isResume
      ? withTimeout(q.initializationResult(), SESSION_VALIDATION_TIMEOUT_MS)
      : undefined;

    const [rawModelOptions] = await Promise.all([
      this.getModelConfigOptions(
        settingsManager.getSettings().model || meta?.model || undefined,
        this.options?.gatewayEnv?.anthropicBaseUrl,
        this.options?.gatewayEnv?.anthropicAuthToken,
      ),
      ...(meta?.taskRunId
        ? [
            this.client.extNotification(POSTHOG_NOTIFICATIONS.SDK_SESSION, {
              taskRunId: meta.taskRunId,
              sessionId,
              adapter: "claude",
            }),
          ]
        : []),
    ]);
    const modelConfigMs = Date.now() - initStartedAt;

    // Restrict the model list to the user's `availableModels` allowlist
    // from settings.json so config UI and downstream resolution stay
    // consistent with what the user configured. The Default option is
    // always preserved per the Claude Code docs.
    const settingsAvailableModels =
      settingsManager.getSettings().availableModels;
    const modelOptions = Array.isArray(settingsAvailableModels)
      ? applyAvailableModelsAllowlist(rawModelOptions, settingsAvailableModels)
      : rawModelOptions;

    if (initPromise) {
      try {
        const initResult = await initPromise;
        if (initResult.result === "timeout") {
          throw new RequestError(
            -32603,
            `Session initialization timed out after ${SESSION_VALIDATION_TIMEOUT_MS}ms`,
            { sessionId, taskId, taskRunId: meta?.taskRunId },
          );
        }
        session.knownSlashCommands = collectKnownSlashCommands(
          initResult.value.commands,
        );
        session.fastModeEnabled = fastModeStateEnabled(
          initResult.value.fast_mode_state,
        );
        this.logger.info("Session initialized", {
          sessionId,
          taskId,
          taskRunId: meta?.taskRunId,
          modelConfigMs,
          initMs: Date.now() - initStartedAt,
        });
      } catch (err) {
        settingsManager.dispose();
        this.terminateQuery(q, abortController);
        this.logger.error("Session initialization failed", {
          sessionId,
          taskId,
          taskRunId: meta?.taskRunId,
          modelConfigMs,
          initMs: Date.now() - initStartedAt,
          errorDetail: serializeError(err),
        });
        throw err;
      }
    }

    const resolvedModelId = resolveInitialModelId(modelOptions, [
      settingsManager.getSettings().model,
      meta?.model,
    ]);
    session.modelId = resolvedModelId;
    session.lastContextWindowSize =
      this.getContextWindowForModel(resolvedModelId);

    const resolvedSdkModel = toSdkModelId(resolvedModelId);

    // New sessions start with options.model = DEFAULT_MODEL, so only a
    // non-default pick needs a setModel call. Resumed sessions always need
    // it: the SDK does not carry the model across resume and would silently
    // run its default otherwise.
    if (isResume || resolvedSdkModel !== DEFAULT_MODEL) {
      await this.session.query.setModel(resolvedSdkModel);
    }

    // Keep thinking enabled by default for effort-capable models (see
    // DEFAULT_EFFORT).
    const resolvedEffort = resolveEffortForModel(resolvedModelId, effort);
    if (resolvedEffort && resolvedEffort !== effort) {
      this.session.effort = resolvedEffort;
      this.session.queryOptions.effort = resolvedEffort;
      await this.session.query.applyFlagSettings({
        // @ts-expect-error SDK Settings.effortLevel omits "max" but runtime accepts it
        effortLevel: resolvedEffort,
      });
    }

    if (supports1MContext(resolvedModelId)) {
      options.betas = ["context-1m-2025-08-07"];
    }

    const availableModes = getAvailableModes();
    const modes: SessionModeState = {
      currentModeId: permissionMode,
      availableModes: availableModes.map((mode) => ({
        id: mode.id,
        name: mode.name,
        description: mode.description ?? undefined,
      })),
    };

    const configOptions = this.buildConfigOptions(
      permissionMode,
      modelOptions,
      this.session.effort ?? DEFAULT_EFFORT,
      session.fastModeEnabled,
    );
    session.configOptions = configOptions;

    if (!creationOpts.skipBackgroundFetches) {
      this.deferBackgroundFetches(q);
    }

    return { sessionId, modes, configOptions };
  }

  private createCanUseTool(
    sessionId: string,
    allowedDomains?: string[],
  ): CanUseTool {
    return async (toolName, toolInput, { suggestions, toolUseID, signal }) =>
      canUseTool({
        session: this.session,
        toolName,
        toolInput: toolInput as Record<string, unknown>,
        toolUseID,
        suggestions,
        signal,
        client: this.client,
        sessionId,
        fileContentCache: this.fileContentCache,
        logger: this.logger,
        updateConfigOption: (configId: string, value: string) =>
          this.updateConfigOption(configId, value),
        applySessionMode: (modeId: string) => this.applySessionMode(modeId),
        allowedDomains,
        emittedToolCalls: this.emittedToolCalls,
        supportsTerminalOutput:
          (
            this.clientCapabilities?._meta as
              | ClientCapabilities["_meta"]
              | undefined
          )?.terminal_output === true,
      });
  }

  private createOnModeChange() {
    return async (newMode: CodeExecutionMode) => {
      if (this.session) {
        const previousMode = this.session.permissionMode;
        this.session.permissionMode = newMode;
        if (newMode === "plan" && previousMode !== "plan") {
          this.session.modeBeforePlan = previousMode;
        }
      }
      await this.updateConfigOption("mode", newMode);
    };
  }

  /** Records the PostHog product behind an executed MCP exec `call` and emits
   *  any newly-seen product so the client's persistent list can update live. */
  private createOnPostHogResourceUsed() {
    return (subTool: string, commandText?: string) => {
      // Surface PostHog calls whose domain we don't recognize yet, so the gap
      // can be closed in `DOMAIN_PRODUCT` rather than the call silently
      // surfacing no chip. Deliberately-suppressed admin domains don't log.
      if (isUnclassifiedPostHogSubTool(subTool)) {
        this.logger.debug("Unclassified PostHog MCP sub-tool", { subTool });
      }
      this.recordSessionResources(
        classifyPostHogExecCall(subTool, commandText),
      );
    };
  }

  /** Adds products to the session-wide set and emits any newly-seen ones.
   *  Session-wide dedup: only the first use of a product emits, so the client's
   *  persistent list shows each chip once across all turns. */
  private recordSessionResources(products: PostHogProductId[]): void {
    if (!this.session) return;
    const added = products.filter((p) => !this.session.sessionResources.has(p));
    if (added.length === 0) return;
    for (const product of added) this.session.sessionResources.add(product);
    void this.emitResourcesUsed(added);
  }

  /** Emits newly-seen PostHog products as soon as they're used, so the client
   *  can append them to a persistent, de-duplicated list in real time. */
  private async emitResourcesUsed(added: PostHogProductId[]): Promise<void> {
    const products = added.map((id) => ({ id, label: POSTHOG_PRODUCTS[id] }));
    await this.client.extNotification(POSTHOG_NOTIFICATIONS.RESOURCES_USED, {
      sessionId: this.sessionId,
      products,
    });
  }

  private getExistingSessionState(
    sessionId: string,
  ): NewSessionResponse | null {
    if (this.sessionId !== sessionId || !this.session) return null;

    const availableModes = getAvailableModes();
    const modes: SessionModeState = {
      currentModeId: this.session.permissionMode,
      availableModes: availableModes.map((mode) => ({
        id: mode.id,
        name: mode.name,
        description: mode.description ?? undefined,
      })),
    };

    return {
      sessionId,
      modes,
      configOptions: this.session.configOptions,
    };
  }

  private buildConfigOptions(
    currentModeId: string,
    modelOptions: {
      currentModelId: string;
      options: SessionConfigSelectOption[];
    },
    currentEffort: EffortLevel = DEFAULT_EFFORT,
    fastModeEnabled?: boolean,
  ): SessionConfigOption[] {
    const modeOptions = getAvailableModes().map((mode) => ({
      value: mode.id,
      name: mode.name,
      description: mode.description ?? undefined,
    }));

    const configOptions: SessionConfigOption[] = [
      {
        id: "mode",
        name: "Approval Preset",
        type: "select",
        currentValue: currentModeId,
        options: modeOptions,
        category: "mode" as SessionConfigOptionCategory,
        description:
          "Choose an approval and sandboxing preset for your session",
      },
      {
        id: "model",
        name: "Model",
        type: "select",
        currentValue: modelOptions.currentModelId,
        options: modelOptions.options,
        category: "model" as SessionConfigOptionCategory,
        description: "Choose which model Claude should use",
      },
    ];

    const effortOptions = getEffortOptions(modelOptions.currentModelId);
    if (effortOptions) {
      configOptions.push({
        id: "effort",
        name: "Effort",
        type: "select",
        currentValue: currentEffort,
        options: effortOptions,
        category: "thought_level" as SessionConfigOptionCategory,
        description: "Controls how much effort Claude puts into its response",
      });
    }

    if (supportsFastMode(modelOptions.currentModelId)) {
      configOptions.push(this.fastModeConfigOption(fastModeEnabled ?? false));
    }

    return configOptions;
  }

  private fastModeConfigOption(enabled: boolean): SessionConfigOption {
    return {
      id: "fast",
      name: "Fast mode",
      type: "select",
      currentValue: enabled ? "on" : "off",
      options: [
        { value: "on", name: "On" },
        { value: "off", name: "Off" },
      ],
      description: "Faster responses on supported models",
    };
  }

  private rebuildFastModeConfigOption(modelId: string): void {
    const withoutFast = this.session.configOptions.filter(
      (o) => o.id !== "fast",
    );
    this.session.configOptions = supportsFastMode(modelId)
      ? [
          ...withoutFast,
          this.fastModeConfigOption(this.session.fastModeEnabled),
        ]
      : withoutFast;
  }

  // Mirror SDK-reported fast mode flips into the config option. A hidden
  // option means the state reflects capability, not intent, and cooldown is
  // transient; neither may touch the retained toggle.
  private async syncFastModeState(
    state: FastModeState | undefined,
  ): Promise<void> {
    if (state === undefined || state === "cooldown") {
      return;
    }
    if (!this.session.configOptions.some((o) => o.id === "fast")) {
      return;
    }
    const enabled = state === "on";
    if (enabled === this.session.fastModeEnabled) {
      return;
    }
    this.session.fastModeEnabled = enabled;
    await this.updateConfigOption("fast", enabled ? "on" : "off");
  }

  // The SDK has no push event for the title it generates in the background,
  // so poll it at turn-end; failures are non-fatal and retried next turn.
  private async maybeUpdateSessionTitle(
    sessionId: string,
    session: Session,
  ): Promise<void> {
    let info: Awaited<ReturnType<typeof getSessionInfo>>;
    try {
      info = await getSessionInfo(sessionId, { dir: session.cwd });
    } catch (error) {
      this.logger.warn("Failed to read session info for title update", {
        sessionId,
        error: error instanceof Error ? error.message : String(error),
      });
      return;
    }
    // customTitle is a user rename; prefer it over the generated summary.
    const rawTitle = info?.customTitle ?? info?.summary;
    if (!rawTitle) {
      return;
    }
    const title = sanitizeTitle(rawTitle);
    if (!title || title === session.lastTitle) {
      return;
    }
    session.lastTitle = title;
    await this.client.sessionUpdate({
      sessionId,
      update: {
        sessionUpdate: "session_info_update",
        title,
        updatedAt: new Date(info?.lastModified ?? Date.now()).toISOString(),
      },
    });
  }

  private rebuildEffortConfigOption(modelId: string): void {
    const effortOptions = getEffortOptions(modelId);
    const existingEffort = this.session.configOptions.find(
      (o) => o.id === "effort",
    );

    if (!effortOptions) {
      this.session.configOptions = this.session.configOptions.filter(
        (o) => o.id !== "effort",
      );
      if (this.session.effort) {
        this.session.effort = undefined;
        this.session.queryOptions.effort = undefined;
        void this.session.query.applyFlagSettings({
          effortLevel: undefined,
        });
      }
      return;
    }

    const rawCurrentValue = existingEffort?.currentValue;
    const currentValue =
      typeof rawCurrentValue === "string" ? rawCurrentValue : DEFAULT_EFFORT;
    const isValidValue = effortOptions.some((o) => o.value === currentValue);
    const resolvedValue = isValidValue ? currentValue : DEFAULT_EFFORT;

    // Set the default when none is chosen yet (see DEFAULT_EFFORT), or re-apply
    // when the prior level is invalid for the newly selected model.
    if (!this.session.effort || resolvedValue !== currentValue) {
      this.session.effort = resolvedValue as EffortLevel;
      this.session.queryOptions.effort = resolvedValue as EffortLevel;
      void this.session.query.applyFlagSettings({
        // @ts-expect-error SDK Settings.effortLevel omits "max" but runtime accepts it
        effortLevel: resolvedValue,
      });
    }

    const effortConfig: SessionConfigOption = {
      id: "effort",
      name: "Effort",
      type: "select",
      currentValue: resolvedValue,
      options: effortOptions,
      category: "thought_level" as SessionConfigOptionCategory,
      description: "Controls how much effort Claude puts into its response",
    };

    if (existingEffort) {
      this.session.configOptions = this.session.configOptions.map((o) =>
        o.id === "effort" ? effortConfig : o,
      );
    } else {
      this.session.configOptions.push(effortConfig);
    }
  }

  private async sendAvailableCommandsUpdate(): Promise<void> {
    const commands = await this.session.query.supportedCommands();
    this.session.knownSlashCommands = collectKnownSlashCommands(commands);
    const available = getAvailableSlashCommands(commands);
    await this.client.sessionUpdate({
      sessionId: this.sessionId,
      update: {
        sessionUpdate: "available_commands_update",
        availableCommands: available,
      },
    });
    this.updateBreakdownCategory("skills", estimateSkillsTokens(available));
  }

  private async refreshSlashCommandsForPrompt(command: string): Promise<void> {
    const commandName = command.slice(1);
    if (this.session.knownSlashCommands?.has(commandName)) {
      return;
    }
    if (commandName.includes(":") || commandName.includes("__")) {
      return;
    }

    try {
      await this.session.query.reloadSkills();
      await this.sendAvailableCommandsUpdate();
    } catch (error) {
      this.logger.warn("Failed to refresh slash commands before prompt", {
        sessionId: this.sessionId,
        command,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  /** Update one category of the context-breakdown baseline so the next
   *  `_posthog/usage_update` carries fresher numbers. No-op when the baseline
   *  hasn't been initialized yet (e.g. in a unit-test session). */
  private updateBreakdownCategory(
    key: keyof NonNullable<Session["contextBreakdownBaseline"]>,
    tokens: number,
  ): void {
    if (!this.session?.contextBreakdownBaseline) return;
    if (this.session.contextBreakdownBaseline[key] === tokens) return;
    this.session.contextBreakdownBaseline = {
      ...this.session.contextBreakdownBaseline,
      [key]: tokens,
    };
  }

  /**
   * Rebuild the in-memory taskState from JSONL and push a plan update so the
   * client's plan panel reflects pre-resume tasks. `loadSession` already covers
   * this via the full `replaySessionHistory` notification stream; resume
   * deliberately stays quiet (the client keeps its own message history) so we
   * walk the transcript here for state only.
   */
  private async rehydrateTaskStateFromJsonl(sessionId: string): Promise<void> {
    try {
      const messages = await getSessionMessages(sessionId, {
        dir: this.session.cwd,
      });
      rehydrateTaskState(messages, this.session.taskState);
      if (this.session.taskState.size === 0) return;
      await this.client.sessionUpdate({
        sessionId,
        update: {
          sessionUpdate: "plan",
          entries: taskStateToPlanEntries(this.session.taskState),
        },
      });
    } catch (err) {
      this.logger.warn("Failed to rehydrate task state", {
        sessionId,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  private async replaySessionHistory(sessionId: string): Promise<void> {
    try {
      const messages = await getSessionMessages(sessionId, {
        dir: this.session.cwd,
      });

      const replayContext = {
        session: this.session,
        sessionId,
        client: this.client,
        toolUseCache: this.toolUseCache,
        emittedToolCalls: this.emittedToolCalls,
        toolUseStreamCache: this.toolUseStreamCache,
        fileContentCache: this.fileContentCache,
        enrichedReadCache: this.enrichedReadCache,
        logger: this.logger,
        registerHooks: false,
        isImportReplay: true,
      };

      for (const msg of messages) {
        const sdkMessage = {
          type: msg.type,
          message: msg.message as {
            content: string | Array<{ type: string; text?: string }>;
            role: typeof msg.type;
          },
          parent_tool_use_id: msg.parent_tool_use_id,
        };
        await handleUserAssistantMessage(
          sdkMessage as Parameters<typeof handleUserAssistantMessage>[0],
          replayContext,
        );
      }
    } catch (err) {
      this.logger.warn("Failed to replay session history", {
        sessionId,
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  // ================================
  // EXTENSION METHODS
  // ================================

  /**
   * Fire-and-forget: fetch slash commands and MCP tool metadata in parallel.
   * Both populate caches used later — neither is needed to return configOptions.
   */
  private deferBackgroundFetches(q: Query): void {
    Promise.all([
      new Promise<void>((resolve) => setTimeout(resolve, 10)).then(() =>
        this.sendAvailableCommandsUpdate(),
      ),
      fetchMcpToolMetadata(q, this.logger).then(() => {
        this.updateBreakdownCategory(
          "mcp",
          estimateMcpTokens(getCachedMcpTools()),
        );
        const serverNames = getConnectedMcpServerNames();
        if (serverNames.length > 0) {
          this.options?.onMcpServersReady?.(serverNames);
        }
      }),
    ]).catch((err) =>
      this.logger.error("Background fetch failed", { error: err }),
    );
  }

  private async broadcastUserMessage(params: PromptRequest): Promise<void> {
    for (const chunk of params.prompt) {
      const notification = {
        sessionId: params.sessionId,
        update: {
          sessionUpdate: "user_message_chunk" as const,
          content: chunk,
        },
      };
      await this.client.sessionUpdate(notification);
      this.appendNotification(params.sessionId, notification);
    }
  }
}
