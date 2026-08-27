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
import { leadingSlashCommand, serializeError } from "@posthog/shared";
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
import type { ContextWikiEnv, PostHogAPIConfig } from "../../types";
import { text } from "../../utils/acp-content";
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
import { isLocalSkillCommandChunk } from "../local-skill";
import { LOCAL_TOOLS_MCP_NAME, type LocalToolCtx } from "../local-tools";
import { visiblePromptBlocks } from "../prompt-blocks";
import {
  resolveBedrockGatewayVariant,
  resolveSpokenNarration,
  resolveTaskId,
} from "../session-meta";
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
import { getSessionJsonlPath } from "./session/jsonl-hydration";
import { parseMcpServers } from "./session/mcp-config";
import {
  applyAvailableModelsAllowlist,
  resolveInitialModelId,
} from "./session/model-config";
import {
  CONTEXT_WINDOW_1M_BETA,
  CONTEXT_WINDOW_200K_TOKENS,
  DEFAULT_EFFORT,
  fastModeStateEnabled,
  getContextWindowOptions,
  getEffortOptions,
  rerootedModelOptions,
  resolveEffortForModel,
  resolveModelPreference,
  supports1MContext,
  supportsFastMode,
  supportsMcpInjection,
} from "./session/models";
import {
  buildSessionOptions,
  buildSystemPrompt,
  type GatewayEnv,
  type ProcessSpawnedInfo,
  toEffortFlagSettings,
  toSdkEffort,
} from "./session/options";
import { SettingsManager } from "./session/settings";
import {
  buildSideQuestionPrompt,
  collectSideQuestionAnswer,
  SIDE_QUESTION_TIMEOUT_MS,
} from "./side-question";
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

// Cap on how long a finished turn waits for the SDK to fold a steer in, so a
// steer stuck in the input queue can't defer the turn forever.
const STEER_DELIVERY_GRACE_MS = 30_000;

const SESSION_ENDED_MESSAGE =
  "The Claude Agent session has ended. Please start a new session.";

const MAX_TITLE_LENGTH = 256;
const LOCAL_ONLY_COMMANDS = new Set(["/context", "/heapdump", "/extra-usage"]);

/**
 * The `/command` a prompt leads with, if any.
 *
 * Read from the ACP prompt rather than the converted SDK message, and skipping
 * the blocks the host injected rather than the user: `promptToClaude` prepends
 * detected-PR and local-skill context, and cloud prompts lead with hidden
 * blocks (the resume preamble; on desktop, shell-execute recaps). Matching the
 * first text block of either would read host context as the user's command and
 * miss the command entirely.
 */
function promptSlashCommand(params: PromptRequest): string | undefined {
  const meta = params._meta as { localSkillName?: unknown } | undefined;
  const localSkillName =
    typeof meta?.localSkillName === "string" ? meta.localSkillName : null;

  for (const chunk of visiblePromptBlocks(params.prompt)) {
    if (chunk.type !== "text") continue;
    // `promptToClaude` consumes this chunk and sends the skill's context in its
    // place, so the SDK never sees a command — neither should we.
    if (localSkillName && isLocalSkillCommandChunk(chunk, localSkillName)) {
      return undefined;
    }
    return leadingSlashCommand(chunk.text);
  }
  return undefined;
}

/** Steers the SDK has yet to fold into the turn. */
function hasUnconsumedSteers(turn: Turn): boolean {
  for (const steer of turn.pendingSteers.values()) {
    if (!steer.consumed) {
      return true;
    }
  }
  return false;
}

/** Ack the steers already folded in: the model has now produced output for them. */
function confirmConsumedSteers(turn: Turn): void {
  for (const [uuid, steer] of turn.pendingSteers) {
    if (steer.consumed) {
      steer.settle(true);
      turn.pendingSteers.delete(uuid);
    }
  }
  if (turn.pendingSteers.size > 0) {
    return;
  }
  if (turn.steerTimer) {
    clearTimeout(turn.steerTimer);
    turn.steerTimer = undefined;
  }
  turn.deferredResult = undefined;
}

/** Report every steer left on a finishing turn as undelivered so callers redeliver it. */
function declinePendingSteers(turn: Turn): void {
  if (turn.steerTimer) {
    clearTimeout(turn.steerTimer);
    turn.steerTimer = undefined;
  }
  for (const steer of turn.pendingSteers.values()) {
    steer.settle(false);
  }
  turn.pendingSteers.clear();
}

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
  /** Per-session context wiki mount — avoids global process.env mutation across concurrent sessions. */
  contextWiki?: ContextWikiEnv;
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
  /**
   * The in-flight side question's controller, so a newer question can abort it.
   * Bounds concurrent forks off the transcript to one.
   */
  private sideQuestionAbort: AbortController | null = null;

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
      // A /btw fork runs on its own controller that the base close path never
      // touches, so without this an in-flight side question keeps streaming
      // (and burning tokens) until its own timeout fires after the session is
      // gone.
      this.sideQuestionAbort?.abort();
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
            // This build implements `/clear` itself and treats a
            // `_posthog/conversation_cleared` marker as a rehydration boundary.
            // Hosts that record the boundary without an agent (the backend does
            // it for a finished cloud run) gate on this: an older agent ignores
            // the marker and would resume the conversation it was meant to
            // retire, so the clear has to look unavailable rather than silently
            // not take.
            conversationClear: true,
            sideQuestion: true,
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
    // Detect local-only slash commands that return results without model invocation
    const command = promptSlashCommand(params);

    if (command === "/clear") {
      // Handled by the adapter, never forwarded to the SDK (whose own /clear
      // is unreliable in this embedding — see UPSTREAM.md "Hide /clear").
      // Ahead of the SDK conversion below, which this path never reads.
      return this.clearConversation(params);
    }

    const userMessage = promptToClaude(params);
    const promptUuid = randomUUID();
    userMessage.uuid = promptUuid;
    const isLocalOnlyCommand = !!command && LOCAL_ONLY_COMMANDS.has(command);

    if (this.session.querySwap) {
      // A /clear or refreshSession is swapping the SDK query underneath. Wait
      // for it to settle so this prompt lands on the fresh input stream, not
      // the retired one (a failed swap sets queryClosed, which the check
      // below rejects). Not the last gate: the awaits before enqueue (slash
      // commands, pre-prompt local-tools) leave this prompt off turnQueue, so
      // a swap can still start there and must be re-checked before enqueue.
      await this.session.querySwap;
    }

    if (command && !isLocalOnlyCommand) {
      await this.refreshSlashCommandsForPrompt(command);
    }

    if (this.session.queryClosed) {
      throw RequestError.internalError(undefined, SESSION_ENDED_MESSAGE);
    }

    const hasInFlightTurns =
      this.session.activeTurn !== null || this.session.turnQueue.length > 0;

    const isSteer = isSteerMeta(params._meta);
    if (hasInFlightTurns && isSteer && !this.session.compacting) {
      // Fold into the running turn (promptToClaude tagged it priority:"now");
      // the benign end_turn is ignored by clients, which key off _meta.steer.
      const owner =
        this.session.activeTurn ??
        this.session.turnQueue.find((turn) => !turn.settled);
      // Decline before pushing, so the message is redelivered rather than also
      // applied by a later turn.
      if (!owner) {
        return { stopReason: "end_turn", _meta: { steer: false } };
      }
      // Only a declined steer is redelivered, so acking on submission loses any
      // steer the SDK never folds in. Wait for the model to act on it instead.
      const ack = new Promise<PromptResponse>((resolve) => {
        owner.pendingSteers.set(promptUuid, {
          consumed: false,
          settle: (reachedModel) =>
            resolve({ stopReason: "end_turn", _meta: { steer: reachedModel } }),
        });
      });
      this.session.input.push(userMessage);
      await this.broadcastUserMessage(params);
      return ack;
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
      pendingSteers: new Map(),
      isLocalOnlyCommand,
      commandName: command,
      broadcast: () => this.broadcastUserMessage(params),
      pendingInput: userMessage,
      settled: false,
      resolve: () => {},
      reject: () => {},
    };
    const response = new Promise<PromptResponse>((resolve, reject) => {
      turn.resolve = resolve;
      turn.reject = reject;
    });

    if (this.session.querySwap) {
      // A swap started during this method's pre-enqueue awaits (the prompt is
      // not yet on turnQueue, so the entry-point refusals don't see it); fail
      // before enqueue rather than push the turn into a retiring stream.
      turn.reject(RequestError.internalError(undefined, SESSION_ENDED_MESSAGE));
      return response;
    }
    if (this.session.queryClosed) {
      turn.reject(RequestError.internalError(undefined, SESSION_ENDED_MESSAGE));
      return response;
    }

    this.session.turnQueue.push(turn);
    this.dispatchQueuedInput(this.session);
    this.ensureConsumer(params.sessionId);
    return response;
  }

  private dispatchQueuedInput(session: Session): void {
    if (session.queryClosed) {
      return;
    }
    if (session.activeTurn && !session.activeTurn.settled) {
      return;
    }
    const head = session.turnQueue.find((turn) => !turn.settled);
    if (!head?.pendingInput) {
      return;
    }
    const input = head.pendingInput;
    head.pendingInput = undefined;
    session.input.push(input);
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
      session.compacting = false;
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
      declinePendingSteers(turn);
      if (session.forceCancelTimer) {
        clearTimeout(session.forceCancelTimer);
        session.forceCancelTimer = undefined;
      }
      session.turnQueue = session.turnQueue.filter((t) => t !== turn);
      session.activeTurn = null;
      this.dispatchQueuedInput(session);
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
      declinePendingSteers(turn);
      session.turnQueue = session.turnQueue.filter((t) => t !== turn);
      session.activeTurn = null;
      this.toolUseStreamCache.clear();
      this.dispatchQueuedInput(session);
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
          declinePendingSteers(turn);
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
              declinePendingSteers(queued);
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
              // Gate the user-facing outcome on `session.compacting` to
              // dedupe the duplicate terminal status the SDK emits for failed
              // compactions.
              if (message.status === "compacting") {
                session.compacting = true;
                // Fall through to handleSystemMessage so the COMPACTING
                // extNotification still fires.
              } else if (
                message.compact_result === "success" &&
                session.compacting
              ) {
                session.compacting = false;
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
                session.compacting
              ) {
                session.compacting = false;
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
                declinePendingSteers(head);
                session.turnQueue = session.turnQueue.filter((t) => t !== head);
                this.dispatchQueuedInput(session);
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
            } else if (
              session.activeTurn &&
              hasUnconsumedSteers(session.activeTurn)
            ) {
              // Only settlement waits on the steer. The refusal and error
              // branches above already returned, and this result's own side
              // effects have run, so nothing is dropped if the turn later
              // settles from the grace timer.
              const deferred = session.activeTurn;
              stopReason = result.stopReason ?? "end_turn";
              deferred.deferredResult = { stopReason, usage: sessionUsage() };
              deferred.steerTimer ??= setTimeout(() => {
                if (session.activeTurn !== deferred) {
                  return;
                }
                this.logger.warn("Steer never reached the model", {
                  sessionId,
                  pendingSteers: deferred.pendingSteers.size,
                });
                settleActive(
                  deferred.deferredResult ?? { stopReason: "end_turn" },
                );
              }, STEER_DELIVERY_GRACE_MS);
              this.logger.debug(
                "Deferring turn completion until pending steers are consumed",
                { sessionId, pendingSteers: deferred.pendingSteers.size },
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
              const steer = session.activeTurn?.pendingSteers.get(message.uuid);
              if (steer) {
                steer.consumed = true;
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
              // Subagent output is a separate model context, so it is no
              // evidence the steer reached this turn's model.
              if (session.activeTurn && message.parent_tool_use_id === null) {
                confirmConsumedSteers(session.activeTurn);
              }
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
    if (session.querySwap) {
      // A /clear or refreshSession is swapping the SDK query: there is no turn
      // to cancel, and interrupting the half-initialized replacement would
      // corrupt the swap. A wedged swap self-limits: retireQuery's interrupt()
      // and the new query's init are both time-bounded (see retireQuery,
      // performClear).
      this.logger.debug("Ignoring cancel while a query swap is in progress", {
        sessionId: this.sessionId,
      });
      return;
    }
    session.cancelled = true;

    // Settle not-yet-echoed turns immediately; the SDK still runs the messages
    // already pushed, so count the echo-less results those owe as orphans.
    for (const turn of [...session.turnQueue]) {
      if (turn === session.activeTurn || turn.settled) {
        continue;
      }
      turn.settled = true;
      declinePendingSteers(turn);
      session.turnQueue = session.turnQueue.filter((t) => t !== turn);
      if (!turn.pendingInput) {
        session.pendingOrphanResults += 1;
      }
      turn.pendingInput = undefined;
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
    if (isMethod(method, POSTHOG_METHODS.SIDE_QUESTION)) {
      if (typeof params.question !== "string" || !params.question.trim()) {
        throw new RequestError(
          -32602,
          "side_question requires a non-empty question",
        );
      }
      return await this.answerSideQuestion(params.question);
    }
    if (isMethod(method, POSTHOG_METHODS.REFRESH_SESSION)) {
      return await this.handleRefreshSession(params);
    }
    throw RequestError.methodNotFound(method);
  }

  private async handleRefreshSession(
    params: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
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

  /** Retire the current consumer and SDK query so a replacement Query can be
   *  swapped in place (refreshSession, clearConversation). The generation bump
   *  makes the retired consumer exit quietly. */
  private async retireQuery(session: Session): Promise<void> {
    session.queryGeneration += 1;
    const oldConsumer = session.consumer;
    session.consumer = undefined;
    session.cancelController?.abort();
    session.cancelController = undefined;

    // Abort FIRST so any stuck in-flight HTTP request unblocks — otherwise
    // interrupt() can deadlock waiting on an API call that never returns.
    // Callers allocate a fresh controller for the new Query so aborting
    // the old one doesn't poison it.
    session.abortController.abort();
    try {
      // Bounded so a wedged interrupt() can't block the swap indefinitely —
      // the abort above should already unblock it; this is the backstop.
      await withTimeout(session.query.interrupt(), 5_000);
    } catch (error) {
      this.logger.debug("Ignoring interrupt error while retiring query", {
        sessionId: this.sessionId,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    session.input.end();
    if (oldConsumer) {
      // Bounded so a wedged old query can't block the swap.
      await withTimeout(oldConsumer, 5_000);
    }
  }

  /**
   * Claim the session's query-swap slot, run `fn`, and release the slot when
   * it settles. The claim is synchronous — `fn` must run synchronously up to
   * its own first await — so the flag is visible before any other ACP handler
   * can interleave (handlers are not serialized). Waiters only need
   * settlement, so the stored promise never rejects; a failure still surfaces
   * through the returned promise.
   */
  private async withQuerySwap<T>(
    session: Session,
    fn: () => Promise<T>,
  ): Promise<T> {
    const swap = fn();
    session.querySwap = swap.then(
      () => undefined,
      () => undefined,
    );
    try {
      return await swap;
    } finally {
      session.querySwap = undefined;
    }
  }

  /**
   * `/clear` — drop the conversation and start over in place.
   *
   * The SDK's own /clear is not forwarded (see UPSTREAM.md "Hide /clear");
   * instead the current Query is retired and a brand-new SDK session (fresh
   * session id, no resume) is swapped in under the same ACP session. The
   * session log stays append-only: a `conversation_cleared` marker records
   * the boundary (rehydration rebuilds only post-clear turns) and an updated
   * `sdk_session` mapping points future resumes at the fresh SDK session.
   */
  private async clearConversation(
    params: PromptRequest,
  ): Promise<PromptResponse> {
    const session = this.session;
    if (session.queryClosed) {
      throw RequestError.internalError(undefined, SESSION_ENDED_MESSAGE);
    }
    // A second swap mid-swap would race the same session fields
    // (query/input/abortController) and orphan a live SDK query; a clear
    // mid-turn would rip the query out from under the active prompt.
    const refusal = session.querySwap
      ? "A session refresh or conversation clear is already in progress. Wait for it to finish and try again."
      : session.activeTurn !== null || session.turnQueue.length > 0
        ? "Cannot clear the conversation while a turn is in progress. Wait for it to finish (or cancel it) and try again."
        : null;
    if (refusal) {
      await this.client.sessionUpdate({
        sessionId: params.sessionId,
        update: {
          sessionUpdate: "agent_message_chunk",
          content: text(refusal),
        },
      });
      return { stopReason: "end_turn" };
    }

    return this.withQuerySwap(session, () =>
      this.performClear(params, session),
    );
  }

  private async performClear(
    params: PromptRequest,
    session: Session,
  ): Promise<PromptResponse> {
    this.logger.info("Clearing conversation", { sessionId: params.sessionId });

    // Signal the in-progress state immediately (mirrors the "compacting"
    // status row): the swap below is normally sub-second, but on a slow or
    // timed-out clear the user would otherwise see no feedback at all
    // between typing `/clear` and either the divider or an error appearing.
    await this.client.extNotification(POSTHOG_NOTIFICATIONS.STATUS, {
      sessionId: params.sessionId,
      status: "clearing",
    });

    let newQuery: Query | undefined;
    let newAbortController: AbortController | undefined;
    try {
      await this.retireQuery(session);

      const newSdkSessionId = uuidv7();
      newAbortController = new AbortController();
      const {
        resume: _dropResume,
        forkSession: _dropFork,
        ...rest
      } = session.queryOptions;

      // Rebuild the in-process ("sdk") server fresh; reusing the prior instance
      // throws "Already connected to a transport".
      const freshInProcess = session.buildInProcessMcpServers();

      const newOptions: Options = {
        ...rest,
        mcpServers: {
          ...externalMcpServers(rest.mcpServers),
          ...freshInProcess,
        },
        sessionId: newSdkSessionId,
        abortController: newAbortController,
        // `rest.model` is the creation-time value; the user may have switched
        // models since, so re-root the new Query on the live session model.
        ...rerootedModelOptions(session.modelId, rest.fallbackModel),
      };

      const newInput = new Pushable<SDKUserMessage>();
      newQuery = query({ prompt: newInput, options: newOptions });

      session.query = newQuery;
      session.input = newInput;
      session.queryOptions = newOptions;
      session.abortController = newAbortController;

      const result = await withTimeout(
        newQuery.initializationResult(),
        SESSION_VALIDATION_TIMEOUT_MS,
      );
      if (result.result === "timeout") {
        throw new Error(
          `Conversation clear timed out after ${SESSION_VALIDATION_TIMEOUT_MS}ms`,
        );
      }
      return await this.finishClear(
        params,
        session,
        newQuery,
        newSdkSessionId,
        result.value,
      );
    } catch (error) {
      // The old query is already retired and the new one is unproven, so any
      // failure here — timeout, SDK init rejection, a consumer that died while
      // being retired — leaves the session unusable. Close it out and report
      // the outcome (same as a failed compaction) rather than leaving the
      // "Clearing…" spinner unresolved and the session half-swapped.
      if (newQuery && newAbortController) {
        this.terminateQuery(newQuery, newAbortController);
      }
      session.queryClosed = true;
      const message = error instanceof Error ? error.message : String(error);
      try {
        await this.client.extNotification(POSTHOG_NOTIFICATIONS.STATUS, {
          sessionId: params.sessionId,
          status: "clearing_failed",
          error: message,
        });
      } catch {
        // The client transport itself is failing; don't mask the cause.
      }
      throw new RequestError(-32603, message, { sessionId: params.sessionId });
    }
  }

  /** Post-swap bookkeeping and notifications once the fresh SDK session is
   *  confirmed live. Failures still propagate to performClear's catch: the
   *  log may already show the /clear, but the session state is authoritative
   *  only once everything (marker included) has been persisted. */
  private async finishClear(
    params: PromptRequest,
    session: Session,
    newQuery: Query,
    newSdkSessionId: string,
    initResult: Awaited<ReturnType<Query["initializationResult"]>>,
  ): Promise<PromptResponse> {
    session.knownSlashCommands = collectKnownSlashCommands(initResult.commands);
    session.fastModeEnabled = fastModeStateEnabled(initResult.fast_mode_state);

    // Future resumes (refreshSession, desktop reconnect, cloud rehydration)
    // must target the fresh SDK session. `this.sessionId` (the ACP-visible
    // id) stays stable — clients keep addressing the session with it.
    const previousSdkSessionId = session.sdkSessionId;
    session.sdkSessionId = newSdkSessionId;

    // Invalidate the jsonl the SDK just finished writing for the retired
    // session — the stable ACP id on a session's first /clear, or that
    // clear's own sdkSessionId on every clear after. Left in place, a cold
    // reconnect that hydrates by that id would find it, skip re-fetching the
    // authoritative log, and resume the pre-clear conversation instead of the
    // cleared one; left on disk, it also orphans one file per clear.
    try {
      await fs.promises.unlink(
        getSessionJsonlPath(previousSdkSessionId, session.cwd),
      );
    } catch (error) {
      // Already gone is the common case (a resumed session that never wrote a
      // local jsonl this run). Anything else means the file survives, and a
      // cold reconnect that finds it resumes the pre-clear conversation — so
      // the clear has to fail rather than report a success the next
      // reconnect quietly undoes.
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }

    const hadTasks = session.taskState.size > 0;
    session.taskState.clear();
    this.toolUseStreamCache.clear();
    this.emittedToolCalls.clear();
    // Nothing from before the boundary should reach the fresh session.
    session.notificationHistory.length = 0;
    session.lastPlanFilePath = undefined;
    this.fileContentCache = {};

    // Only broadcast (and thus persist) the "/clear" prompt once the new
    // session is confirmed live — the log must never show a "/clear" whose
    // clear never actually happened. Broadcast before the marker so it lands
    // on the pre-clear side of the rehydration boundary and gets dropped
    // rather than replayed as a turn after resume.
    await this.broadcastUserMessage(params);

    // These notifications are independent of one another (only the
    // user-message broadcast above must precede them); issue them
    // concurrently rather than paying sequential round trips.
    const postClearNotifications: Promise<unknown>[] = [
      // Clear the "Clearing…" spinner. `conversation_cleared` normally
      // supersedes it visually, but signal completion explicitly (same
      // rationale as the compacting spinner) rather than relying on that.
      this.client.extNotification(POSTHOG_NOTIFICATIONS.STATUS, {
        sessionId: params.sessionId,
        status: "clearing",
        isComplete: true,
      }),
    ];
    if (session.taskRunId) {
      postClearNotifications.push(
        this.client.extNotification(POSTHOG_NOTIFICATIONS.SDK_SESSION, {
          taskRunId: session.taskRunId,
          sessionId: newSdkSessionId,
          adapter: "claude",
        }),
      );
    }
    postClearNotifications.push(
      this.client.extNotification(POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED, {
        sessionId: newSdkSessionId,
      }),
    );
    if (hadTasks) {
      postClearNotifications.push(
        this.client.sessionUpdate({
          sessionId: params.sessionId,
          update: { sessionUpdate: "plan", entries: [] },
        }),
      );
    }
    postClearNotifications.push(
      this.client.sessionUpdate({
        sessionId: params.sessionId,
        update: {
          sessionUpdate: "usage_update",
          used: 0,
          size:
            session.lastContextWindowSize ??
            this.getContextWindowForModel(session.modelId ?? ""),
        },
      }),
    );
    await Promise.all(postClearNotifications);

    this.refreshMcpMetadata(newQuery);
    return { stopReason: "end_turn" };
  }

  /**
   * Answers a "/btw" side question by forking the live session's transcript
   * into a one-shot, tool-less, single-turn query. Strictly non-mutating:
   * the fork gets its own SDK session id and AbortController, and nothing on
   * `this.session` is touched, so the main conversation (including an
   * in-flight turn) never sees the exchange.
   *
   * A newer question supersedes an in-flight one: the card shows only the
   * latest, so answering a question it has already replaced burns tokens on
   * a result the stale-answer guard would discard anyway.
   */
  private async answerSideQuestion(
    question: string,
  ): Promise<{ answer: string }> {
    this.sideQuestionAbort?.abort();

    const abortController = new AbortController();
    this.sideQuestionAbort = abortController;
    try {
      // Drop `sessionId` (identity comes from `resume`), `hooks` (they close
      // over live-session caches and task state), and `outputFormat` (a
      // structured task run stores a json_schema here that would force the
      // plain-text answer into the task's unrelated shape).
      const {
        sessionId: _sessionId,
        hooks: _hooks,
        outputFormat: _outputFormat,
        ...rest
      } = this.session.queryOptions;
      const options: Options = {
        ...rest,
        // Fork the current SDK session, not the stable ACP id. `/clear` swaps
        // `sdkSessionId` to a fresh session and deletes the pre-clear
        // transcript, so `this.sessionId` would resume a retired one.
        resume: this.session.sdkSessionId,
        forkSession: true,
        maxTurns: 1,
        // Belt and braces: remove the toolset entirely and deny anything
        // that slips through; the prompt wrapper also says "no tools".
        tools: [],
        allowedTools: [],
        canUseTool: async () => ({
          behavior: "deny",
          message: "Tools are unavailable while answering a side question.",
          interrupt: false,
        }),
        // Never reuse in-process MCP instances ("Already connected to a
        // transport"); the fork has no tools, so it needs no servers.
        mcpServers: {},
        // `mcpServers: {}` alone only drops the servers passed in code — the
        // CLI would still merge `.mcp.json`, user settings, and plugin/agent
        // frontmatter servers back in.
        strictMcpConfig: true,
        // A side question is an isolated read of the transcript, so nothing
        // the repo can write should get to run for it. `settingSources: []`
        // keeps `.claude/settings*.json` (and the hooks they declare) off the
        // fork, and plugins and agents ship their own hooks and skills.
        settingSources: [],
        plugins: [],
        agents: {},
        abortController,
        // `rest.model` is the creation-time value; the user may have
        // switched models since, so answer on the live session model.
        ...rerootedModelOptions(this.session.modelId, rest.fallbackModel),
      };

      const oneShot = query({
        prompt: buildSideQuestionPrompt(question),
        options,
      });

      const answer = await withTimeout(
        collectSideQuestionAnswer(oneShot),
        SIDE_QUESTION_TIMEOUT_MS,
      );

      if (answer.result === "timeout") {
        throw new RequestError(
          -32603,
          `Side question timed out after ${SIDE_QUESTION_TIMEOUT_MS}ms`,
        );
      }
      if (!answer.value) {
        throw new RequestError(-32603, "Side question produced no answer");
      }
      return { answer: answer.value };
    } catch (error) {
      if (error instanceof RequestError) throw error;
      // A brand-new session has no transcript on disk yet, so `resume` has
      // nothing to fork; surface that case clearly.
      throw new RequestError(
        -32603,
        `Side question failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      abortController.abort();
      if (this.sideQuestionAbort === abortController) {
        this.sideQuestionAbort = null;
      }
    }
  }

  private refreshSession(
    mcpServers: Record<string, McpServerConfig>,
  ): Promise<void> {
    const prev = this.session;
    if (prev.querySwap) {
      throw new RequestError(
        -32002,
        "Cannot refresh session while a query swap (refresh or /clear) is in progress",
      );
    }
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

    return this.withQuerySwap(prev, () =>
      this.performRefresh(prev, mcpServers),
    );
  }

  /** Body of {@link refreshSession}; see {@link withQuerySwap} for the claim
   *  contract. */
  private async performRefresh(
    prev: Session,
    mcpServers: Record<string, McpServerConfig>,
  ): Promise<void> {
    this.logger.info("Refreshing session with fresh MCP servers", {
      serverCount: Object.keys(mcpServers).length,
      sessionId: this.sessionId,
    });

    // Declared outside the try so the catch can tear down a half-built
    // replacement; assigned inside, where retireQuery also runs so a failure
    // anywhere in the swap gets the same close-out (mirrors performClear).
    let newQuery: Query | undefined;
    let newAbortController: AbortController | undefined;
    try {
      await this.retireQuery(prev);

      // Reuse every option from the running session; swap mcpServers, re-root
      // identity on `resume` instead of `sessionId`, and give the new Query a
      // fresh AbortController.
      newAbortController = new AbortController();
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
        resume: prev.sdkSessionId,
        forkSession: false,
        abortController: newAbortController,
        // `rest.model` is the creation-time value; the user may have switched
        // models since, so re-root the new Query on the live session model.
        ...rerootedModelOptions(prev.modelId, rest.fallbackModel),
      };

      const newInput = new Pushable<SDKUserMessage>();
      newQuery = query({ prompt: newInput, options: newOptions });

      prev.query = newQuery;
      prev.input = newInput;
      prev.queryOptions = newOptions;
      prev.abortController = newAbortController;

      const result = await withTimeout(
        newQuery.initializationResult(),
        SESSION_VALIDATION_TIMEOUT_MS,
      );
      if (result.result === "timeout") {
        throw new Error(
          `Session refresh timed out after ${SESSION_VALIDATION_TIMEOUT_MS}ms`,
        );
      }
    } catch (error) {
      // The old query is already retired and the new one is unproven, so any
      // failure here — retireQuery, timeout, or SDK init rejection — leaves
      // the session unusable. Tear down any replacement that was allocated
      // and close the session out (same as performClear) rather than leaving
      // it half-swapped: queryClosed gates every later prompt into
      // SESSION_ENDED.
      if (newQuery && newAbortController) {
        this.terminateQuery(newQuery, newAbortController);
      }
      prev.queryClosed = true;
      const message = error instanceof Error ? error.message : String(error);
      throw new RequestError(-32603, message, { sessionId: this.sessionId });
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
      await this.session.query.setModel(resolvedValue);
      this.session.modelId = resolvedValue;
      this.session.lastContextWindowSize =
        this.getContextWindowForModel(resolvedValue);
      this.rebuildEffortConfigOption(resolvedValue);
      this.rebuildContextWindowConfigOption(resolvedValue);
      this.rebuildFastModeConfigOption(resolvedValue);
    } else if (params.configId === "effort") {
      const newEffort = resolvedValue as EffortLevel;
      this.session.effort = newEffort;
      this.session.queryOptions.effort = toSdkEffort(newEffort);
      await this.session.query.applyFlagSettings(
        toEffortFlagSettings(newEffort),
      );
    } else if (params.configId === "context_window") {
      const enable1M = resolvedValue === "1m";
      // queryOptions is read per prompt, so this applies from the next turn.
      this.session.queryOptions.betas = enable1M
        ? [CONTEXT_WINDOW_1M_BETA]
        : undefined;
      this.session.lastContextWindowSize = enable1M
        ? this.getContextWindowForModel(this.session.modelId ?? "")
        : CONTEXT_WINDOW_200K_TOKENS;
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
    // queryOptions seeds every later query rebuild (/clear, refreshSession), so the
    // mode has to land there too. Left stale, a rebuild restores the creation-time
    // mode — handing back permissions the user had since narrowed, with nothing on
    // screen to say so.
    this.session.queryOptions.permissionMode = toSdkPermissionMode(
      modeId as CodeExecutionMode,
    );
    if (modeId === "plan" && previousMode !== "plan") {
      this.session.modeBeforePlan = previousMode;
      // A new planning cycle must not resolve against the prior cycle's plan
      // file. Left set, an ExitPlanMode before this cycle's first plan write
      // reads the old file, which passes validation and gets approved.
      this.session.lastPlanFilePath = undefined;
    }
    try {
      await this.session.query.setPermissionMode(
        toSdkPermissionMode(modeId as CodeExecutionMode),
      );
    } catch (error) {
      this.session.permissionMode = previousMode;
      this.session.queryOptions.permissionMode =
        toSdkPermissionMode(previousMode);
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

    // The session's explicit pick outranks the shared claude settings file:
    // that file is cross-session state and must only ever be a fallback.
    const earlyModelId =
      meta?.model || settingsManager.getSettings().model || "";

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
    const channelMode = meta?.channelMode;
    const taskOriginProduct =
      typeof meta?.taskOriginProduct === "string"
        ? meta.taskOriginProduct
        : undefined;
    const endRunWhenDone = meta?.endRunWhenDone === true;
    const spokenNarration = resolveSpokenNarration(meta);
    const bedrockGatewayVariant = resolveBedrockGatewayVariant(meta);
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
          channelMode,
          spokenNarration,
          background: meta?.mode === "background",
          peerMessaging: process.env.POSTHOG_AGENT_PEER_MESSAGING === "1",
          taskOriginProduct,
          endRunWhenDone,
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
      contextWikiPath: this.options?.contextWiki?.path,
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
      getCurrentModelId: () => this.session?.modelId,
      gatewayEnv: this.options?.gatewayEnv,
      bedrockGatewayVariant,
      contextWiki: this.options?.contextWiki,
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
      sdkSessionId: sessionId,
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
    const requestedModel =
      meta?.model || settingsManager.getSettings().model || undefined;

    const [rawModelOptions] = await Promise.all([
      this.getModelConfigOptions(
        requestedModel,
        this.options?.gatewayEnv?.anthropicBaseUrl,
        this.options?.gatewayEnv?.anthropicAuthToken,
        Number(this.options?.gatewayEnv?.posthogProjectId) || undefined,
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
        const initMs = Date.now() - initStartedAt;
        this.logger.error("Session initialization failed", {
          sessionId,
          taskId,
          taskRunId: meta?.taskRunId,
          initializationPhase: "sdk_initialization",
          timeoutMs: SESSION_VALIDATION_TIMEOUT_MS,
          modelConfigMs,
          initMs,
          requestedModel: requestedModel ?? null,
          gatewayConfigured: Boolean(
            this.options?.gatewayEnv?.anthropicBaseUrl,
          ),
          errorDetail: serializeError(err),
        });
        throw err;
      }
    }

    const resolvedModelId = resolveInitialModelId(modelOptions, [
      meta?.model,
      settingsManager.getSettings().model,
    ]);
    modelOptions.currentModelId = resolvedModelId;
    session.modelId = resolvedModelId;
    session.lastContextWindowSize =
      meta?.contextWindow === "200k"
        ? CONTEXT_WINDOW_200K_TOKENS
        : this.getContextWindowForModel(resolvedModelId);

    if (isResume || resolvedModelId !== options.model) {
      await this.session.query.setModel(resolvedModelId);
    }

    // Keep thinking enabled by default for effort-capable models (see
    // DEFAULT_EFFORT).
    const resolvedEffort = resolveEffortForModel(resolvedModelId, effort);
    // Ultracode re-applies even when the requested effort stands: the flag
    // only reaches the session through applyFlagSettings.
    if (
      resolvedEffort &&
      (resolvedEffort !== effort || resolvedEffort === "ultracode")
    ) {
      this.session.effort = resolvedEffort;
      this.session.queryOptions.effort = toSdkEffort(resolvedEffort);
      await this.session.query.applyFlagSettings(
        toEffortFlagSettings(resolvedEffort),
      );
    }

    if (supports1MContext(resolvedModelId) && meta?.contextWindow !== "200k") {
      options.betas = [CONTEXT_WINDOW_1M_BETA];
    }

    if (meta?.fastMode && supportsFastMode(resolvedModelId)) {
      this.session.fastModeEnabled = true;
      await this.session.query.applyFlagSettings({ fastMode: true });
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
        // Same reason as applySessionMode: queryOptions seeds every later
        // rebuild, and this path (the EnterPlanMode hook) moves the mode too.
        this.session.queryOptions.permissionMode = toSdkPermissionMode(newMode);
        if (newMode === "plan" && previousMode !== "plan") {
          this.session.modeBeforePlan = previousMode;
          // Same reason as applySessionMode: a new cycle must not inherit the
          // prior cycle's plan file.
          this.session.lastPlanFilePath = undefined;
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

  /** Matches the ACP session id, or the underlying SDK session id after a
   *  /clear (desktop hosts re-key on the sdk_session notification). */
  hasSession(sessionId: string): boolean {
    return (
      super.hasSession(sessionId) || this.session?.sdkSessionId === sessionId
    );
  }

  private getExistingSessionState(
    sessionId: string,
  ): NewSessionResponse | null {
    if (!this.hasSession(sessionId) || !this.session) return null;

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
      // Echo the canonical ACP session id even if the caller matched via the
      // post-/clear SDK session id (see hasSession) — clients must keep
      // addressing the session with the stable id.
      sessionId: this.sessionId,
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

    const contextOption = this.contextWindowConfigOption(
      modelOptions.currentModelId,
    );
    if (contextOption) {
      configOptions.push(contextOption);
    }

    if (supportsFastMode(modelOptions.currentModelId)) {
      configOptions.push(this.fastModeConfigOption(fastModeEnabled ?? false));
    }

    return configOptions;
  }

  private contextWindowConfigOption(
    modelId: string,
  ): SessionConfigOption | null {
    const contextOptions = getContextWindowOptions(modelId);
    if (!contextOptions) return null;
    const is1M = this.session.queryOptions.betas?.includes(
      CONTEXT_WINDOW_1M_BETA,
    );
    return {
      id: "context_window",
      name: "Context Window",
      type: "select",
      currentValue: is1M ? "1m" : "200k",
      options: contextOptions,
      category: "_context_window" as SessionConfigOptionCategory,
      description: "Choose the context window size for this session",
    };
  }

  private rebuildContextWindowConfigOption(modelId: string): void {
    const withoutContext = this.session.configOptions.filter(
      (o) => o.id !== "context_window",
    );
    if (!supports1MContext(modelId)) {
      this.session.queryOptions.betas = undefined;
      this.session.configOptions = withoutContext;
      return;
    }
    // Switching onto a 1M-capable model restores the default 1M window.
    this.session.queryOptions.betas = [CONTEXT_WINDOW_1M_BETA];
    const contextOption = this.contextWindowConfigOption(modelId);
    this.session.configOptions = contextOption
      ? [...withoutContext, contextOption]
      : withoutContext;
  }

  private fastModeConfigOption(enabled: boolean): SessionConfigOption {
    return {
      id: "fast",
      name: "Fast Mode",
      type: "select",
      currentValue: enabled ? "on" : "off",
      options: [
        { value: "on", name: "On" },
        { value: "off", name: "Off" },
      ],
      category: "_fast_mode" as SessionConfigOptionCategory,
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
      // The SDK stores session info under the SDK session id, which diverges
      // from the client-addressed id after a /clear.
      info = await getSessionInfo(session.sdkSessionId, {
        dir: session.cwd,
      });
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
          ultracode: false,
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
      const resolvedEffort = resolvedValue as EffortLevel;
      this.session.effort = resolvedEffort;
      this.session.queryOptions.effort = toSdkEffort(resolvedEffort);
      void this.session.query.applyFlagSettings(
        toEffortFlagSettings(resolvedEffort),
      );
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
