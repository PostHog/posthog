import { createHash } from "node:crypto";
import { access, cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import type {
  ContentBlock,
  PromptResponse,
  RequestPermissionRequest,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";
import {
  ClientSideConnection,
  ndJsonStream,
  PROTOCOL_VERSION,
} from "@agentclientprotocol/sdk";
import { type ServerType, serve } from "@hono/node-server";
import { execGh } from "@posthog/git/gh";
import { getCurrentBranch, getRemoteUrl } from "@posthog/git/queries";
import { ghTokenEnv } from "@posthog/git/signed-commit";
import {
  type AcpMcpServer,
  type Adapter,
  buildPrOutput,
  getErrorMessage,
  isIgnoredSkillPath,
  isSkillBundleArtifactMetadata,
  type McpServerConnection,
  mergePrUrls,
  parseMcpToolName,
  readMcpToolDescriptor,
  readPrUrls,
  sleepWithBackoff,
  toAcpMcpServers,
} from "@posthog/shared";
import {
  buildPosthogPropertiesHeaderLines,
  buildPosthogPropertiesHeaderRecord,
  buildPosthogScopedPropertyHeaderLines,
  buildPosthogScopedPropertyHeaderRecord,
} from "@posthog/shared/posthog-property-headers";
import { prependProductEngineerPrompt } from "@posthog/shared/product-engineer-prompt";
import { appendRichOutputPrompt } from "@posthog/shared/rich-output-prompt";
import { unzipSync } from "fflate";
import { Hono } from "hono";
import { z } from "zod";
import packageJson from "../../package.json" with { type: "json" };
import { POSTHOG_METHODS, POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import {
  createAcpConnection,
  type InProcessAcpConnection,
} from "../adapters/acp-connection";
import { setAlwaysAskMcpServers } from "../adapters/claude/mcp/tool-metadata";
import {
  getSessionJsonlPath,
  hydrateSessionJsonl,
} from "../adapters/claude/session/jsonl-hydration";
import type { GatewayEnv } from "../adapters/claude/session/options";
import { codexKeyMatchesMcpServerName } from "../adapters/codex-app-server/mcp-config";
import { hasCodexThreadState } from "../adapters/codex-app-server/thread-state";
import {
  type AgentErrorClassification,
  classifyAgentError,
  isPromptTooLongError,
} from "../adapters/error-classification";
import { GH_STACK_QUALIFIED_TOOL_NAME } from "../adapters/local-tools/tools/gh-stack";
import { isSupportedReasoningEffort } from "../adapters/reasoning-effort";
import { appendRtkGuidanceForCodex } from "../adapters/rtk-guidance";
import {
  SIGNED_COMMIT_QUALIFIED_TOOL_NAME,
  SIGNED_MERGE_QUALIFIED_TOOL_NAME,
  SIGNED_REWRITE_QUALIFIED_TOOL_NAME,
} from "../adapters/signed-commit-shared";
import type { PermissionMode } from "../execution-mode";
import { DEFAULT_CODEX_MODEL, fetchGatewayModels } from "../gateway-models";
import { OtelRunTelemetry } from "../otel-telemetry";
import { configurePersistentAgentState } from "../persistent-agent-state";
import { PostHogAPIClient } from "../posthog-api";
import {
  compilePostHogExecPermissionRegex,
  DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
  extractPostHogSubTool,
  isPostHogExecDescriptor,
  matchesPostHogExecPermission,
} from "../posthog-exec-permission";
import {
  findPrUrls,
  type OwnedBranch,
  parsePrRepository,
  wasCreatedByThisRun,
} from "../pr-url-detector";
import {
  formatConversationForResume,
  type ResumeState,
  resumeFromLog,
} from "../resume";
import { SessionLogWriter } from "../session-log-writer";
import type {
  AgentMode,
  DeviceInfo,
  LogLevel,
  Task,
  TaskRun,
  TaskRunArtifact,
  TaskRunState,
  TaskRunStateField,
} from "../types";
import { resourceLink } from "../utils/acp-content";
import { AsyncMutex } from "../utils/async-mutex";
import { withTimeout } from "../utils/common";
import { resolveGatewayProduct, resolveGatewayTarget } from "../utils/gateway";
import { resolveGithubToken } from "../utils/github-token";
import { Logger } from "../utils/logger";
import { logAgentshRuntimeInfo } from "./agentsh-runtime";
import { AgentBootTracker } from "./boot-phases";
import {
  normalizeCloudPromptContent,
  promptBlocksToText,
} from "./cloud-prompt";
import { TaskRunEventStreamSender } from "./event-stream-sender";
import { type JwtPayload, JwtValidationError, validateJwt } from "./jwt";
import { type McpRelayResponse, McpRelayServer } from "./mcp-relay-server";
import {
  checkoutExistingPullRequest,
  type ExistingPrCheckoutResult,
} from "./pr-checkout";
import { resolveRtkSavings } from "./rtk-savings";
import { RunUsageAccumulator } from "./run-usage";
import { jsonRpcRequestSchema, validateCommandParams } from "./schemas";
import type { AgentServerConfig, ClaudeCodeConfig } from "./types";
import { waitForFile } from "./wait-for-file";

const agentErrorClassificationSchema = z.enum([
  "upstream_stream_terminated",
  "upstream_connection_error",
  "upstream_timeout",
  "upstream_provider_failure",
  "turn_ended_without_response",
  "agent_error",
]) satisfies z.ZodType<AgentErrorClassification>;

const INITIAL_TASK_RUN_REFRESH_TIMEOUT_MS = 5_000;

export const UPSTREAM_PROVIDER_FAILURE_MESSAGE =
  "The upstream AI provider failed to process the request. Please retry the task in a few minutes.";

const upstreamProviderFailureClassifications =
  new Set<AgentErrorClassification>([
    "upstream_stream_terminated",
    "upstream_connection_error",
    "upstream_timeout",
    "upstream_provider_failure",
  ]);

const errorWithClassificationSchema = z.object({
  data: z.object({ classification: agentErrorClassificationSchema }),
});

type MessageCallback = (message: unknown) => void;

export const SSE_KEEPALIVE_INTERVAL_MS = 25_000;

// Bounded per-turn retries for unattended (initial/resume) turns that hit a
// transient upstream failure. Two covers a retry whose own attempt also gets
// cut once, without letting a hard upstream outage loop forever.
const MAX_UPSTREAM_TURN_RETRIES = 2;
const UPSTREAM_TURN_RETRY_DELAY_MS = 5_000;
const PENDING_ARTIFACT_MAX_ATTEMPTS = 4;
const PENDING_ARTIFACT_RETRY_DELAY_MS = 500;

export function buildCloudSessionSystemPrompt(
  cloudAppend: string,
  userPrompt: ClaudeCodeConfig["systemPrompt"],
): string | { append: string } {
  const prompt = [
    typeof userPrompt === "string" ? userPrompt : userPrompt?.append,
    cloudAppend,
  ]
    .filter(Boolean)
    .join("\n\n");
  const combinedPrompt = appendRichOutputPrompt(
    prependProductEngineerPrompt(prompt),
  );

  return typeof userPrompt === "string"
    ? combinedPrompt
    : { append: combinedPrompt };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class NdJsonTap {
  private decoder = new TextDecoder();
  private buffer = "";

  constructor(private onMessage: MessageCallback) {}

  process(chunk: Uint8Array): void {
    this.buffer += this.decoder.decode(chunk, { stream: true });
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        this.onMessage(JSON.parse(line));
      } catch {
        // Not valid JSON, skip
      }
    }
  }
}

function createTappedReadableStream(
  underlying: ReadableStream<Uint8Array>,
  onMessage: MessageCallback,
  logger?: Logger,
): ReadableStream<Uint8Array> {
  const reader = underlying.getReader();
  const tap = new NdJsonTap(onMessage);

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { value, done } = await reader.read();
        if (done) {
          controller.close();
          return;
        }
        tap.process(value);
        controller.enqueue(value);
      } catch (error) {
        logger?.debug("Read failed, closing stream", error);
        controller.close();
      }
    },
    cancel() {
      reader.releaseLock();
    },
  });
}

function createTappedWritableStream(
  underlying: WritableStream<Uint8Array>,
  onMessage: MessageCallback,
  logger?: Logger,
): WritableStream<Uint8Array> {
  const tap = new NdJsonTap(onMessage);
  const mutex = new AsyncMutex();

  return new WritableStream<Uint8Array>({
    async write(chunk) {
      tap.process(chunk);
      await mutex.acquire();
      try {
        const writer = underlying.getWriter();
        await writer.write(chunk);
        writer.releaseLock();
      } catch (error) {
        logger?.debug("Write failed (stream may be closed)", error);
      } finally {
        mutex.release();
      }
    },
    async close() {
      await mutex.acquire();
      try {
        const writer = underlying.getWriter();
        await writer.close();
        writer.releaseLock();
      } catch (error) {
        logger?.debug("Close failed (stream may be closed)", error);
      } finally {
        mutex.release();
      }
    },
    async abort(reason) {
      await mutex.acquire();
      try {
        const writer = underlying.getWriter();
        await writer.abort(reason);
        writer.releaseLock();
      } catch (error) {
        logger?.debug("Abort failed (stream may be closed)", error);
      } finally {
        mutex.release();
      }
    },
  });
}

export function isTurnCompleteNotification(message: unknown): boolean {
  return (
    typeof message === "object" &&
    message !== null &&
    (message as { method?: unknown }).method ===
      POSTHOG_NOTIFICATIONS.TURN_COMPLETE
  );
}

interface SseController {
  send: (data: unknown) => void;
  close: () => void;
}

interface ActiveSession {
  payload: JwtPayload;
  acpSessionId: string;
  acpConnection: InProcessAcpConnection;
  clientConnection: ClientSideConnection;
  sseController: SseController | null;
  deviceInfo: DeviceInfo;
  logWriter: SessionLogWriter;
  /** Ships run telemetry (logs + spans) to PostHog; unset when the sandbox has no OTLP config */
  telemetry?: OtelRunTelemetry;
  /** Current permission mode, tracked for relay decisions */
  permissionMode: PermissionMode;
  /** Whether a desktop client has ever connected via SSE during this session */
  hasDesktopConnected: boolean;
  /** Meta the session was created with, reused when a retry needs a fresh session */
  sessionMeta: Record<string, unknown>;
}

interface InstalledSkillBundle {
  skillName: string;
  skillDefinition: string;
  contentSha256: string;
  skillRoot: string;
}

interface BuiltPrompt {
  prompt: ContentBlock[];
  meta?: Record<string, unknown>;
  messageId?: string;
}

export const PREWARMED_RESUME_IDLE_CAPABILITY = "prewarmedResumeIdle";

function hiddenTextBlock(text: string): ContentBlock {
  return {
    type: "text",
    text,
    _meta: { ui: { hidden: true } },
  } as ContentBlock;
}

function isManualCompactPrompt(prompt: ContentBlock[]): boolean {
  return /^\/compact(?:\s|$)/.test(promptBlocksToText(prompt).trimStart());
}

/** True when the agent implements `/clear` and honours the conversation-cleared boundary. */
function extractConversationClearCapability(result: unknown): boolean {
  return (
    (
      result as {
        agentCapabilities?: {
          _meta?: { posthog?: { conversationClear?: unknown } };
        };
      }
    )?.agentCapabilities?._meta?.posthog?.conversationClear === true
  );
}

function extractSteeringCapability(result: unknown): string | undefined {
  const steering = (
    result as {
      agentCapabilities?: { _meta?: { posthog?: { steering?: unknown } } };
    }
  )?.agentCapabilities?._meta?.posthog?.steering;
  return typeof steering === "string" ? steering : undefined;
}

interface LocalSkillPromptContext {
  /** Set when the message is a bare `/skill` invocation the adapter should strip. */
  skillName?: string;
  context: string;
}

function getTaskRunStateString(
  taskRun: TaskRun | null,
  key: TaskRunStateField,
): string | null {
  const value = taskRun?.state[key];
  return typeof value === "string" ? value : null;
}

type SteerDeclineReason =
  | "startup_turn"
  | "no_active_turn"
  | "adapter_rejected";

/** Which delivery routes a Slack run has, as resolved by the backend from flags and Slack scopes. */
type SlackArtifactDelivery = "none" | "message" | "canvas_file";

const SLACK_ARTIFACT_DELIVERY_MODES: SlackArtifactDelivery[] = [
  "none",
  "message",
  "canvas_file",
];

/**
 * An unset key means the backend told us nothing — any non-Slack run, or a Slack run that
 * predates this. Emit no constraints rather than guessing: the agent must never be offered a
 * route delivery would reject, nor told it has none while it actually does.
 */
function readSlackArtifactDelivery(
  taskRun: TaskRun | null,
): SlackArtifactDelivery | null {
  const mode = getTaskRunStateString(taskRun, "slack_artifact_delivery");
  return SLACK_ARTIFACT_DELIVERY_MODES.find((known) => known === mode) ?? null;
}

/**
 * Charts ride on their own key rather than a delivery mode: they need only the rollout
 * flag, while canvas and file delivery also needs Slack scopes that are still in review,
 * so a workspace can have charts and nothing else. Absent or non-boolean means a backend
 * that predates charts, which is the same as off.
 */
function readSlackChartDelivery(taskRun: TaskRun | null): boolean {
  return taskRun?.state.slack_chart_delivery === true;
}

// Prompt block we hand the agent when the user attached files but we could not
// load any of them into the session (missing from the run manifest, no storage
// path, etc.). Without this the caller falls back to the bare task description —
// e.g. "Attached files: pasted-text.txt" — which points the agent at files it
// was never given and makes it hunt the filesystem in vain. Be explicit instead.
function buildMissingAttachmentNotice(count: number): string {
  const subject = count === 1 ? "A file" : `${count} files`;
  const pronoun = count === 1 ? "it" : "they";
  const noun = count === 1 ? "attachment" : "attachments";
  return (
    `${subject} the user attached to this message could not be loaded into the session, ` +
    `so ${pronoun} are unavailable here. Do not guess at the contents. Tell the user the ` +
    `${noun} didn't come through, and ask them to paste the text directly or send ${pronoun} again.`
  );
}

/**
 * The codex session's LLM auth, from the resolved gateway env. Codex must never
 * read the raw run credential: on the Go-gateway path the bearer is the per-run
 * scoped token (see configureEnvironment).
 */
export function codexAuthFromGatewayEnv(env: GatewayEnv): {
  apiBaseUrl: string;
  apiKey: string;
} {
  return { apiBaseUrl: env.openaiBaseUrl, apiKey: env.openaiApiKey };
}

interface PrAttribution {
  createdAt: string | null;
  author: string | null;
  headRefName: string | null;
  isCrossRepository: boolean | null;
}

const GITHUB_REMOTE_REGEX = /github\.com[:/]([^/\s]+\/[^/\s]+?)(?:\.git)?\/?$/i;

export function parseGithubRemoteRepository(
  remoteUrl: string | null | undefined,
): string | null {
  if (!remoteUrl) return null;
  const match = GITHUB_REMOTE_REGEX.exec(remoteUrl.trim());
  return match ? match[1].toLowerCase() : null;
}

// Branches the run has pushed, as recorded on its task run by signed commits
// (`output.head_branches`, per repository) and by the branch sync
// (`output.head_branch`, repository unknown). This is what proves ownership when
// the agent-server has no checkout of its own, as in no-repository mode.
export function ownedBranchesFromOutput(
  output: Record<string, unknown> | null | undefined,
): OwnedBranch[] {
  if (!output) return [];
  const owned: OwnedBranch[] = [];
  const listed = output.head_branches;
  if (Array.isArray(listed)) {
    for (const entry of listed) {
      if (!entry || typeof entry !== "object") continue;
      const { repository, branch } = entry as {
        repository?: unknown;
        branch?: unknown;
      };
      if (typeof branch !== "string" || !branch) continue;
      owned.push({
        repository:
          typeof repository === "string" && repository
            ? repository.trim().toLowerCase()
            : null,
        branch,
      });
    }
  }
  if (typeof output.head_branch === "string" && output.head_branch) {
    owned.push({ repository: null, branch: output.head_branch });
  }
  return owned;
}

export class AgentServer {
  private config: AgentServerConfig;
  private sessionReadyBootMs?: number;
  private sessionInitMs?: number;
  private barrierReleasedAtMs?: number;
  private bootTracker: AgentBootTracker;
  private logger: Logger;
  private server: ServerType | null = null;
  private session: ActiveSession | null = null;
  private app: Hono;
  private posthogAPI: PostHogAPIClient;
  private eventStreamSender: TaskRunEventStreamSender | null = null;
  private rtkSavingsAttempted = false;
  private questionRelayedToSlack = false;
  private adapterEmittedTurnComplete = false;
  private suppressAdapterTurnComplete = false;
  private runUsage = new RunUsageAccumulator();
  private detectedPrUrl: string | null = null;
  private slackArtifactDelivery: SlackArtifactDelivery | null = null;
  private slackChartDelivery = false;
  private taskRepositories: string[] = [];
  // Reset per session. `evaluatedPrUrls` dedupes per URL; `prAttributionChain` serializes
  // attributions so the most recently created PR in a run wins.
  private readonly evaluatedPrUrls = new Set<string>();
  private prAttributionChain: Promise<void> = Promise.resolve();
  private lastReportedBranch: string | null = null;
  private resumeState: ResumeState | null = null;
  private nativeResume: { sessionId: string; warm: boolean } | null = null;
  private oversizedResumeRetried = false;
  // Prewarmed runs boot before the user's first message exists, so boot-time
  // CLI flags can't carry the user's choice. Those settings are read from the
  // run's state when the first message arrives (see resolveActivationSettings).
  private prewarmedRun = false;
  private prewarmedStartupTurnPending = false;
  private autoPublishStateResolved = false;
  private warmReasoningEffortResolved = false;
  private installedSkillBundles = new Set<string>();
  private installedSkillBundleInfo = new Map<string, InstalledSkillBundle>();
  private installingSkillBundles = new Map<string, Promise<void>>();
  // Guards against concurrent session initialization. autoInitializeSession() and
  // the GET /events SSE handler can both call initializeSession() — the SSE connection
  // often arrives while newSession() is still awaited (this.session is still null),
  // causing a second session to be created and duplicate Slack messages to be sent.
  private initializationPromise: Promise<void> | null = null;
  private initializingTelemetry: OtelRunTelemetry | undefined;
  private pendingEvents: Record<string, unknown>[] = [];
  /** ACP notifications emitted by newSession/resumeSession before this.session is assigned. */
  private preSessionEvents: Record<string, unknown>[] = [];
  private deliveredMessageIds = new Set<string>();
  private pendingCompactContinuationMessageIds = new Set<string>();
  private inFlightMessageDeliveries = new Map<string, Promise<unknown>>();
  private activeOwnedTurnCount = 0;
  private activeStartupTurnCount = 0;
  // Normal follow-ups own turns in arrival order. Explicit steering bypasses
  // this tail so it can still reach the active adapter turn immediately.
  private nonSteerDeliveryTail: Promise<void> = Promise.resolve();
  private pendingPermissions = new Map<
    string,
    {
      resolve: (response: {
        outcome: { outcome: "selected"; optionId: string };
        _meta?: Record<string, unknown>;
      }) => void;
      toolCallId?: string;
      optionIds: Set<string>;
      /**
       * Question responses carry synthetic `option_<idx>`/submit ids built by
       * the client from the question `_meta`, not from the relayed options, so
       * the offered-option check must not apply to them.
       */
      validateOptionIds: boolean;
    }
  >();
  private readonly posthogExecPermissionRegex: RegExp;
  private readonly posthogExecPermissionRegexSource: string;
  private mcpRelayServer: McpRelayServer | null = null;

  /**
   * Start loopback relay endpoints for the run's designated desktop-only MCP
   * servers and return their session mcpServers entries. No designations →
   * no relay server, no entries.
   */
  private async startMcpRelayServer(): Promise<McpServerConnection[]> {
    const names = this.config.relayMcpServers ?? [];
    if (names.length === 0) return [];
    if (!this.mcpRelayServer) {
      this.mcpRelayServer = new McpRelayServer({
        servers: names,
        emitEvent: (event) => this.broadcastEvent(event),
        hasReachableClient: () => this.hasReachableClient(),
        logger: this.logger,
      });
      await this.mcpRelayServer.start();
      // Relayed tools execute on the user's machine — always ask.
      setAlwaysAskMcpServers(names);
    }
    return this.mcpRelayServer.mcpServers;
  }

  private detachSseController(controller: SseController): void {
    if (this.session?.sseController === controller) {
      this.session.sseController = null;
    }
  }

  private emitConsoleLog = (
    level: LogLevel,
    _scope: string,
    message: string,
    data?: unknown,
  ): void => {
    if (!this.session) return;

    const formatted =
      data !== undefined ? `${message} ${JSON.stringify(data)}` : message;

    const notification = {
      jsonrpc: "2.0",
      method: POSTHOG_NOTIFICATIONS.CONSOLE,
      params: { level, message: formatted },
    };

    this.broadcastEvent({
      type: "notification",
      timestamp: new Date().toISOString(),
      notification,
    });

    this.session.logWriter.appendRawLine(
      this.session.payload.run_id,
      JSON.stringify(notification),
    );
  };

  constructor(config: AgentServerConfig) {
    this.config = config;
    this.bootTracker = new AgentBootTracker(config.runId);
    this.posthogExecPermissionRegexSource =
      config.posthogExecPermissionRegex ??
      DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE;
    this.posthogExecPermissionRegex = compilePostHogExecPermissionRegex(
      this.posthogExecPermissionRegexSource,
    );
    this.logger = new Logger({ debug: true, prefix: "[AgentServer]" });
    this.posthogAPI = new PostHogAPIClient({
      apiUrl: config.apiUrl,
      projectId: config.projectId,
      getApiKey: () => config.apiKey,
      userAgent: `posthog/cloud.hog.dev; version: ${config.version ?? packageJson.version}`,
    });
    if (config.eventIngestToken) {
      this.eventStreamSender = new TaskRunEventStreamSender({
        apiUrl: config.apiUrl,
        eventIngestBaseUrl: config.eventIngestBaseUrl,
        keepProxyStreamOpen: config.eventIngestKeepStreamOpen,
        projectId: config.projectId,
        taskId: config.taskId,
        runId: config.runId,
        token: config.eventIngestToken,
        logger: this.logger.child("EventIngest"),
        streamWindowMs: config.eventIngestStreamWindowMs,
      });
    }
    this.app = this.createApp();
  }

  private getRuntimeAdapter(): Adapter {
    return this.config.runtimeAdapter ?? "claude";
  }

  private getEffectiveMode(payload: JwtPayload): AgentMode {
    return payload.mode ?? this.config.mode;
  }

  /**
   * Ships run telemetry to PostHog when the sandbox provides an OTLP endpoint
   * + token (POSTHOG_AGENT_OTEL_LOGS_URL/_TOKEN): metadata log records, plus an
   * APM trace per run when POSTHOG_AGENT_OTEL_TRACES_URL is also set. Resource
   * attributes carry the run/user identifiers so cloud runs are filterable per
   * user, task, and run in the Logs UI. Returns undefined when unconfigured or
   * on failure — telemetry must never block session startup.
   */
  private createRunTelemetry(
    payload: JwtPayload,
    deviceInfo: DeviceInfo,
    adapter: "claude" | "codex",
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
          deviceType: deviceInfo.type,
          teamId: payload.team_id,
          userId: payload.user_id,
          distinctId: payload.distinct_id,
          adapter,
          mode: this.getEffectiveMode(payload),
          agentVersion: this.config.version ?? packageJson.version,
        },
        new Logger({ debug: false, prefix: "[OtelRunTelemetry]" }),
      );
    } catch (error) {
      this.logger.warn("Failed to initialize OTel run telemetry", error);
      return undefined;
    }
  }

  private getSessionPermissionMode(): PermissionMode {
    if (this.session?.permissionMode) {
      return this.session.permissionMode;
    }

    return this.getRuntimeAdapter() === "codex" ? "auto" : "default";
  }

  // A direct SSE viewer or an active durable event stream both count: the
  // desktop reads the durable stream through the agent-proxy without ever
  // connecting to the sandbox, so requiring hasDesktopConnected alone would
  // 503/auto-deny every relayed request and permission prompt.
  private hasReachableClient(): boolean {
    return (
      Boolean(this.session?.hasDesktopConnected) ||
      this.eventStreamSender !== null
    );
  }

  private shouldRelayPermissionToClient(mode: PermissionMode): boolean {
    // "plan" relays like "read-only" (look-don't-touch): escalations need a human
    // veto, not silent auto-approval.
    return (
      mode === "default" ||
      mode === "read-only" ||
      mode === "plan" ||
      // codex relays every approval, so relaying "auto" prompts for what it runs unattended.
      (mode === "auto" && this.getRuntimeAdapter() !== "codex")
    );
  }

  private createApp(): Hono {
    const app = new Hono();

    app.get("/health", (c) => {
      const boot = this.bootTracker.snapshot();
      return c.json({
        status: "ok",
        hasSession: !!this.session,
        readiness: boot.state,
        bootMs: this.sessionReadyBootMs,
        sessionInitMs: this.sessionInitMs,
        boot,
        capabilities: [PREWARMED_RESUME_IDLE_CAPABILITY],
      });
    });

    app.get("/events", async (c) => {
      let payload: JwtPayload;

      try {
        payload = this.authenticateRequest(c.req.header.bind(c.req));
      } catch (error) {
        return c.json(
          {
            error:
              error instanceof JwtValidationError
                ? error.message
                : "Invalid token",
            code:
              error instanceof JwtValidationError
                ? error.code
                : "invalid_token",
          },
          401,
        );
      }

      let keepaliveInterval: ReturnType<typeof setInterval> | null = null;
      const clearKeepalive = (): void => {
        if (keepaliveInterval) {
          clearInterval(keepaliveInterval);
          keepaliveInterval = null;
        }
      };

      const stream = new ReadableStream({
        start: async (controller) => {
          let sseController: SseController | null = null;
          const encoder = new TextEncoder();
          const detachCurrentSseController = (): void => {
            if (sseController) {
              this.detachSseController(sseController);
            }
          };
          const enqueueSseFrame = (frame: string): void => {
            try {
              controller.enqueue(encoder.encode(frame));
            } catch {
              clearKeepalive();
              detachCurrentSseController();
            }
          };

          sseController = {
            send: (data: unknown) => {
              enqueueSseFrame(`data: ${JSON.stringify(data)}\n\n`);
            },
            close: () => {
              try {
                clearKeepalive();
                controller.close();
              } catch {
                detachCurrentSseController();
              }
            },
          };

          keepaliveInterval = setInterval(() => {
            enqueueSseFrame(": keepalive\n\n");
          }, SSE_KEEPALIVE_INTERVAL_MS);

          try {
            if (
              !this.session ||
              this.session.payload.run_id !== payload.run_id
            ) {
              await this.initializeSession(payload, sseController);
            } else {
              this.session.sseController = sseController;
              this.session.hasDesktopConnected = true;
              this.replayPendingEvents();
            }

            this.sendSseEvent(sseController, {
              type: "connected",
              run_id: payload.run_id,
            });
          } catch (error) {
            clearKeepalive();
            throw error;
          }
        },
        cancel: () => {
          clearKeepalive();
          this.logger.debug("SSE connection closed");
          if (this.session?.sseController) {
            this.session.sseController = null;
          }
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

    app.post("/command", async (c) => {
      let payload: JwtPayload;

      try {
        payload = this.authenticateRequest(c.req.header.bind(c.req));
      } catch (error) {
        return c.json(
          {
            error:
              error instanceof JwtValidationError
                ? error.message
                : "Invalid token",
          },
          401,
        );
      }

      if (!this.session || this.session.payload.run_id !== payload.run_id) {
        return c.json({ error: "No active session for this run" }, 400);
      }

      const rawBody = await c.req.json().catch(() => null);
      const parseResult = jsonRpcRequestSchema.safeParse(rawBody);

      if (!parseResult.success) {
        return c.json({ error: "Invalid JSON-RPC request" }, 400);
      }

      const command = parseResult.data;
      const paramsValidation = validateCommandParams(
        command.method,
        command.params ?? {},
      );

      if (!paramsValidation.success) {
        return c.json(
          {
            jsonrpc: "2.0",
            id: command.id,
            error: {
              code: -32602,
              message: paramsValidation.error,
            },
          },
          200,
        );
      }

      try {
        const result = await this.executeCommand(
          command.method,
          (command.params as Record<string, unknown>) || {},
        );
        return c.json({
          jsonrpc: "2.0",
          id: command.id,
          result,
        });
      } catch (error) {
        return c.json({
          jsonrpc: "2.0",
          id: command.id,
          error: {
            code: -32000,
            message: error instanceof Error ? error.message : "Unknown error",
          },
        });
      }
    });

    app.notFound((c) => {
      return c.json({ error: "Not found" }, 404);
    });

    return app;
  }

  async start(): Promise<void> {
    if (this.config.agentStateDir) {
      await configurePersistentAgentState(this.config.agentStateDir);
    }

    await new Promise<void>((resolve) => {
      this.server = serve(
        {
          fetch: this.app.fetch,
          port: this.config.port,
        },
        () => {
          this.logger.debug(
            `HTTP server listening on port ${this.config.port}`,
            { bootMs: Math.round(process.uptime() * 1000) },
          );
          resolve();
        },
      );
    });

    await this.autoInitializeSession();
  }

  private async loadResumeState(
    taskId: string,
    resumeRunId: string,
    currentRunId: string,
  ): Promise<void> {
    this.logger.debug("Loading resume state", { resumeRunId, currentRunId });
    try {
      this.resumeState = await resumeFromLog({
        taskId,
        runId: resumeRunId,
        repositoryPath: this.config.repositoryPath,
        apiClient: this.posthogAPI,
        logger: new Logger({ debug: true, prefix: "[Resume]" }),
      });
      this.logger.debug("Resume state loaded", {
        conversationTurns: this.resumeState.conversation.length,
        logEntries: this.resumeState.logEntryCount,
      });
    } catch (error) {
      this.logger.debug("Failed to load resume state, starting fresh", {
        error,
      });
      this.resumeState = null;
    }
  }

  private async prepareNativeResume(
    payload: JwtPayload,
    posthogAPI: PostHogAPIClient,
    preTaskRun: TaskRun | null,
    runtimeAdapter: Adapter,
    cwd: string,
    permissionMode: PermissionMode,
  ): Promise<{ sessionId: string; warm: boolean } | null> {
    const resumeRunId = this.getResumeRunId(preTaskRun);
    if (!resumeRunId) return null;

    if (!this.resumeState) {
      await this.loadResumeState(payload.task_id, resumeRunId, payload.run_id);
    }

    const priorSessionId = this.resumeState?.sessionId ?? null;
    if (!priorSessionId) {
      this.logger.debug("No prior session id; using summary resume fallback", {
        resumeRunId,
      });
      return null;
    }

    if (runtimeAdapter === "codex") {
      // Codex owns thread persistence in CODEX_HOME (the ACP sessionId is the
      // codex thread id). The rollout only survives a snapshot restart — there
      // is no cold hydration equivalent, so a fresh sandbox keeps the summary
      // fallback while a warm one resumes the thread natively via thread/resume.
      if (!(await hasCodexThreadState(priorSessionId))) {
        this.logger.debug(
          "No codex thread state on disk; using summary resume fallback",
          { resumeRunId, priorSessionId },
        );
        return null;
      }
      this.logger.debug("Native codex resume prepared", { priorSessionId });
      return { sessionId: priorSessionId, warm: true };
    }

    let warm = false;
    try {
      await access(getSessionJsonlPath(priorSessionId, cwd));
      warm = true;
    } catch {
      warm = false;
    }

    try {
      const { hasSession } = await hydrateSessionJsonl({
        sessionId: priorSessionId,
        cwd,
        taskId: payload.task_id,
        runId: resumeRunId,
        model: this.config.model,
        permissionMode,
        posthogAPI,
        log: {
          info: (msg, data) => this.logger.debug(msg, data),
          warn: (msg, data) => this.logger.warn(msg, data),
        },
      });
      if (!hasSession) {
        this.logger.debug(
          "No session JSONL to resume; using summary fallback",
          {
            resumeRunId,
            priorSessionId,
          },
        );
        return null;
      }
    } catch (error) {
      this.logger.warn(
        "Session JSONL hydration failed; using summary fallback",
        {
          priorSessionId,
          error: error instanceof Error ? error.message : String(error),
        },
      );
      return null;
    }

    this.logger.debug("Native resume prepared", { priorSessionId, warm });
    return { sessionId: priorSessionId, warm };
  }

  private getNativeGoalForFreshSession(
    runtimeAdapter: Adapter,
  ): ResumeState["nativeGoal"] {
    if (runtimeAdapter !== "codex") return undefined;
    return this.resumeState?.nativeGoal;
  }

  async stop(): Promise<void> {
    this.logger.debug("Stopping agent server...");

    if (this.session) {
      await this.cleanupSession({ completeEventStream: true });
    } else {
      await this.eventStreamSender?.stop();
    }

    if (this.server) {
      this.server.close();
      this.server = null;
    }

    this.logger.debug("Agent server stopped");
  }

  /**
   * Mark the run failed after an unrecoverable crash (uncaught exception /
   * unhandled rejection). Without this a hard death is silent: the run row
   * stays non-terminal, the desktop client just sees the stream stop and shows
   * a generic "Cloud stream disconnected", and the workflow only gives up after
   * the multi-hour inactivity timeout. Best-effort and self-contained so it can
   * run from a process-level handler with no session context.
   */
  async reportFatalError(error: unknown): Promise<void> {
    const errorMessage = error instanceof Error ? error.message : String(error);
    this.logger.error("Fatal agent-server error; marking run failed", error);

    try {
      await this.posthogAPI.updateTaskRun(
        this.config.taskId,
        this.config.runId,
        {
          status: "failed",
          error_message: `Agent server crashed: ${errorMessage}`,
        },
      );
    } catch (updateError) {
      this.logger.error(
        "Failed to mark run failed after fatal error",
        updateError,
      );
    }

    try {
      await this.eventStreamSender?.stop();
    } catch (stopError) {
      this.logger.error(
        "Failed to flush event stream after fatal error",
        stopError,
      );
    }

    // Mirror the crash into run telemetry and shut it down (ends the root
    // span as errored and flushes) - the process is about to die, so nothing
    // else will get this record out.
    try {
      const session = this.session;
      if (session?.telemetry) {
        session.telemetry.append(session.payload.run_id, {
          type: "notification",
          timestamp: new Date().toISOString(),
          notification: {
            jsonrpc: "2.0",
            method: POSTHOG_NOTIFICATIONS.ERROR,
            params: {
              source: "agent_server_crash",
              error: `Agent server crashed: ${errorMessage}`,
            },
          },
        });
        await session.telemetry.shutdown();
      }
    } catch (telemetryError) {
      this.logger.error(
        "Failed to flush telemetry after fatal error",
        telemetryError,
      );
    }
  }

  private authenticateRequest(
    getHeader: (name: string) => string | undefined,
  ): JwtPayload {
    // Always require JWT validation - never trust unverified headers
    if (!this.config.jwtPublicKey) {
      throw new JwtValidationError(
        "Server not configured with JWT public key",
        "server_error",
      );
    }

    const authHeader = getHeader("authorization");
    if (!authHeader?.startsWith("Bearer ")) {
      throw new JwtValidationError(
        "Missing authorization header",
        "invalid_token",
      );
    }

    const token = authHeader.slice(7);
    return validateJwt(token, this.config.jwtPublicKey);
  }

  private async executeCommand(
    method: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    if (!this.session) {
      throw new Error("No active session");
    }

    switch (method) {
      case POSTHOG_NOTIFICATIONS.USER_MESSAGE:
      case "user_message": {
        const commandSession = this.session;
        const messageId =
          typeof params.messageId === "string" && params.messageId
            ? params.messageId
            : undefined;
        const inFlightDelivery = messageId
          ? this.inFlightMessageDeliveries.get(messageId)
          : undefined;
        if (inFlightDelivery) {
          this.logger.info("Awaiting in-flight user_message delivery", {
            messageId,
          });
          return await inFlightDelivery;
        }

        let retryCompactContinuation = false;
        if (messageId && this.deliveredMessageIds.has(messageId)) {
          if (this.pendingCompactContinuationMessageIds.has(messageId)) {
            retryCompactContinuation = true;
            this.logger.info("Retrying pending compact continuation", {
              messageId,
            });
          } else {
            this.logger.info("Duplicate user_message delivery ignored", {
              messageId,
            });
            return { stopReason: "duplicate_delivery", duplicate: true };
          }
        }

        let resolveDelivery: (result: unknown) => void = () => {};
        let rejectDelivery: (error: unknown) => void = () => {};
        const deliveryOutcome = new Promise<unknown>((resolve, reject) => {
          resolveDelivery = resolve;
          rejectDelivery = reject;
        });
        void deliveryOutcome.catch(() => {});
        if (messageId) {
          this.inFlightMessageDeliveries.set(messageId, deliveryOutcome);
        }
        let releaseNonSteerDelivery: (() => void) | undefined;
        const commitDelivery = (): void => {
          if (!messageId) return;
          this.markMessageDelivered(messageId);
        };

        try {
          if (params.steer !== true) {
            releaseNonSteerDelivery = await this.acquireNonSteerDeliveryTurn();
          }
          this.logger.debug("Received user_message command", {
            hasContent:
              typeof params.content === "string"
                ? params.content.trim().length > 0
                : Array.isArray(params.content) && params.content.length > 0,
            artifactCount: Array.isArray(params.artifacts)
              ? params.artifacts.length
              : 0,
          });
          const builtPrompt = await this.buildPromptFromContentAndArtifacts({
            content: params.content as string | ContentBlock[] | undefined,
            artifacts: Array.isArray(params.artifacts)
              ? (params.artifacts as TaskRunArtifact[])
              : [],
            taskId: commandSession.payload.task_id,
            runId: commandSession.payload.run_id,
          });
          let prompt = builtPrompt.prompt;
          if (prompt.length === 0) {
            throw new Error("User message cannot be empty");
          }

          this.logger.debug("Built user_message prompt", {
            blockTypes: prompt.map((block) => block.type),
          });
          const promptPreview = promptBlocksToText(prompt);

          this.logger.debug(
            `Processing user message (detectedPrUrl=${this.detectedPrUrl ?? "none"}): ${promptPreview.substring(0, 100)}...`,
          );

          // Apply activation-time settings before the warmed agent sees its
          // first prompt. The sandbox and session can be prepared with one
          // effort while the final composer selection uses another.
          // Resolve before buildDetectedPrContext so a warm auto-publish upgrade
          // also flips the detected-PR context to its push variant.
          const autoPublishUpgrade = await this.resolveActivationSettings();
          const hostContext = [
            ...(autoPublishUpgrade ? [autoPublishUpgrade] : []),
            ...(this.detectedPrUrl
              ? [this.buildDetectedPrContext(this.detectedPrUrl)]
              : []),
          ];
          const promptMeta: Record<string, unknown> = {
            ...(builtPrompt.meta ?? {}),
            ...(hostContext.length > 0
              ? { prContext: hostContext.join("\n\n") }
              : {}),
          };

          if (params.steer === true) {
            let declineReason: SteerDeclineReason = "no_active_turn";
            if (this.activeStartupTurnCount > 0) {
              declineReason = "startup_turn";
            } else if (this.activeOwnedTurnCount > 0) {
              const result = await commandSession.clientConnection.prompt({
                sessionId: commandSession.acpSessionId,
                prompt,
                _meta: { ...promptMeta, steer: true },
              });
              const accepted =
                (result._meta as { steer?: unknown } | undefined)?.steer ===
                true;
              if (accepted) {
                commitDelivery();
                const outcome = { stopReason: "steered", steered: true };
                resolveDelivery(outcome);
                return outcome;
              }
              declineReason = "adapter_rejected";
            }
            const outcome = {
              stopReason: "steer_declined",
              steered: false,
              reason: declineReason,
            };
            resolveDelivery(outcome);
            return outcome;
          }

          // Read the slash command off what the user actually typed. A deferred summary resume
          // prepends a hidden history block, and `isManualCompactPrompt` matches on the whole
          // prompt text, so checking afterwards would stop recognizing `/compact` as the first
          // message of a resumed session.
          const manualCompactPrompt = isManualCompactPrompt(prompt);

          const deferredResume = await this.preparePrewarmedResumePrompt(
            commandSession.payload,
            prompt,
          );
          prompt = deferredResume.prompt;

          commandSession.logWriter.resetTurnMessages(
            commandSession.payload.run_id,
          );

          const acpSessionId = commandSession.acpSessionId;
          const continueAfterCompaction = (): Promise<PromptResponse> =>
            this.promptWithUpstreamRetry({
              sessionId: acpSessionId,
              prompt: [
                hiddenTextBlock(
                  "Compaction is complete. Continue working on the task from the compacted context, following the user's instructions from the /compact command.",
                ),
              ],
            });

          let result: PromptResponse;
          this.suppressAdapterTurnComplete =
            manualCompactPrompt || retryCompactContinuation;
          try {
            if (retryCompactContinuation) {
              result = await this.runOwnedTurn(continueAfterCompaction);
              if (messageId) {
                this.pendingCompactContinuationMessageIds.delete(messageId);
              }
            } else {
              const runPrompt = () => {
                const promptResult = commandSession.clientConnection.prompt({
                  sessionId: commandSession.acpSessionId,
                  prompt,
                  ...(Object.keys(promptMeta).length > 0
                    ? { _meta: promptMeta }
                    : {}),
                });
                if (!promptResult) {
                  throw new Error("Agent connection did not accept the prompt");
                }
                return promptResult;
              };
              const runTurn = () => {
                if (this.prewarmedStartupTurnPending) {
                  this.prewarmedStartupTurnPending = false;
                  return this.runStartupTurn(runPrompt);
                }
                return this.runOwnedTurn(runPrompt);
              };
              try {
                result = await runTurn();
              } catch (error) {
                // A deferred native resume replays the whole prior transcript, which can overflow
                // the context window. Fall back the way `sendResumeContinuation` does — a fresh
                // session carrying summarized history — instead of failing the run.
                const retryPrompt =
                  deferredResume.consumed && isPromptTooLongError(error)
                    ? await this.retryOversizedDeferredResume(
                        commandSession.payload,
                        builtPrompt.prompt,
                      )
                    : null;
                if (!retryPrompt) {
                  throw error;
                }
                prompt = retryPrompt;
                result = await runTurn();
              }

              if (result.stopReason === "end_turn" && manualCompactPrompt) {
                commitDelivery();
                if (messageId) {
                  this.pendingCompactContinuationMessageIds.add(messageId);
                }
                // `/compact` is an SDK-local command, so without a follow-up the
                // cloud run reports completion before the model resumes the task.
                this.recordTurnUsage(result.usage);
                result = await this.runOwnedTurn(continueAfterCompaction);
                if (messageId) {
                  this.pendingCompactContinuationMessageIds.delete(messageId);
                }
              }
            }
          } catch (error) {
            await commandSession.logWriter.flushAll();
            const { recoverable } = await this.handleTurnFailure(
              commandSession.payload,
              "followup",
              error,
            );
            if (!recoverable) {
              throw error;
            }
            commitDelivery();
            if (deferredResume.consumed) {
              this.resumeState = null;
              this.nativeResume = null;
            }
            const outcome = { stopReason: "error_recoverable" };
            resolveDelivery(outcome);
            return outcome;
          } finally {
            this.suppressAdapterTurnComplete = false;
          }
          commitDelivery();
          if (deferredResume.consumed) {
            this.resumeState = null;
            this.nativeResume = null;
          }

          this.logger.debug("User message completed", {
            stopReason: result.stopReason,
          });

          if (result.stopReason === "end_turn") {
            void this.syncCloudBranchMetadata(commandSession.payload);
          }

          this.recordTurnUsage(result.usage);
          this.broadcastTurnComplete(result.stopReason);

          if (result.stopReason === "end_turn") {
            // Relay the response to Slack. For follow-ups this is the primary
            // delivery path — the HTTP caller only handles reactions. Echo the
            // initiating message's id so the backend can attribute the answer.
            this.relayAgentResponse(commandSession.payload, messageId).catch(
              (err) =>
                this.logger.debug("Failed to relay follow-up response", err),
            );
          }

          // Flush logs and include the assistant's response text so callers
          // (e.g. Slack follow-up forwarding) can extract it without racing
          // against async log persistence to object storage.
          let assistantMessage: string | undefined;
          try {
            await commandSession.logWriter.flush(
              commandSession.payload.run_id,
              {
                coalesce: true,
              },
            );
            assistantMessage = commandSession.logWriter.getFullAgentResponse(
              commandSession.payload.run_id,
            );
          } catch {
            this.logger.debug("Failed to extract assistant message from logs");
          }

          const outcome = {
            stopReason: result.stopReason,
            ...(assistantMessage && { assistant_message: assistantMessage }),
          };
          resolveDelivery(outcome);
          return outcome;
        } catch (error) {
          rejectDelivery(error);
          throw error;
        } finally {
          releaseNonSteerDelivery?.();
          if (
            messageId &&
            this.inFlightMessageDeliveries.get(messageId) === deliveryOutcome
          ) {
            this.inFlightMessageDeliveries.delete(messageId);
          }
        }
      }

      case POSTHOG_NOTIFICATIONS.CANCEL:
      case "cancel": {
        this.logger.debug("Cancel requested", {
          acpSessionId: this.session.acpSessionId,
        });
        await this.session.clientConnection.cancel({
          sessionId: this.session.acpSessionId,
        });
        return { cancelled: true };
      }

      case POSTHOG_NOTIFICATIONS.CLOSE:
      case "close": {
        this.logger.debug("Close requested");
        await this.cleanupSession();
        return { closed: true };
      }

      case "posthog/set_config_option":
      case "set_config_option": {
        const configId = params.configId as string;
        const value = params.value as string;

        this.logger.debug("Set config option requested", { configId, value });

        const result =
          await this.session.clientConnection.setSessionConfigOption({
            sessionId: this.session.acpSessionId,
            configId,
            value,
          });

        return {
          configOptions: result.configOptions,
        };
      }

      case POSTHOG_METHODS.REFRESH_SESSION:
      case "posthog/refresh_session":
      case "refresh_session": {
        const mcpServers = Array.isArray(params.mcpServers)
          ? params.mcpServers
          : [];
        const refreshedCredentials = Array.isArray(params.refreshedCredentials)
          ? (params.refreshedCredentials as string[])
          : [];
        const authorship =
          typeof params.authorship === "string" ? params.authorship : "";

        if (refreshedCredentials.length > 0) {
          const owner = authorship ? ` (${authorship})` : "";
          this.logger.debug(
            `Refreshed sandbox credentials${owner}: ${refreshedCredentials.join(", ")}`,
          );
        }

        if (mcpServers.length === 0) {
          return { refreshed: true };
        }

        // refresh_session replaces the session's MCP server list wholesale, and
        // Django's refresh rebuilds it from posthog + user + imported configs —
        // it can't include the relay loopback entries, whose URL and per-run
        // bearer live only here. Re-append them so a mid-run refresh (token
        // rotation, follow-up past the refresh window) doesn't silently drop
        // every relayed server from the session.
        const relayServers = this.mcpRelayServer?.mcpServers ?? [];
        const refreshedMcpServers = [
          ...mcpServers,
          ...relayServers.filter(
            (relay) =>
              !mcpServers.some(
                (s: { name?: unknown }) => s?.name === relay.name,
              ),
          ),
        ];

        this.logger.debug("Refresh session requested", {
          serverCount: refreshedMcpServers.length,
          relayServerCount: relayServers.length,
        });

        return await this.session.clientConnection.extMethod(
          POSTHOG_METHODS.REFRESH_SESSION,
          { mcpServers: toAcpMcpServers(refreshedMcpServers) },
        );
      }

      case POSTHOG_METHODS.SIDE_QUESTION:
      case "side_question": {
        const question = params.question as string;

        this.logger.debug("Side question requested");

        // Returned as the command result rather than emitted as a session
        // update: a side question is ephemeral, so it must not reach the
        // event stream or the persisted transcript.
        return await this.session.clientConnection.extMethod(
          POSTHOG_METHODS.SIDE_QUESTION,
          { sessionId: this.session.acpSessionId, question },
        );
      }

      case POSTHOG_NOTIFICATIONS.PERMISSION_RESPONSE:
      case "permission_response": {
        const requestId = params.requestId as string;
        const optionId = params.optionId as string;
        const customInput = params.customInput as string | undefined;
        const answers = params.answers as Record<string, string> | undefined;

        this.logger.debug("Permission response received", {
          requestId,
          optionId,
        });

        const resolved = this.resolvePermission(
          requestId,
          optionId,
          customInput,
          answers,
        );
        if (resolved === "not_found") {
          throw new Error(
            `No pending permission request found for id: ${requestId}`,
          );
        }
        if (resolved === "invalid_option") {
          throw new Error(
            `Option "${optionId}" was not offered for permission request ${requestId}`,
          );
        }
        return { resolved: true };
      }

      case POSTHOG_NOTIFICATIONS.MCP_RESPONSE:
      case "mcp_response": {
        const resolved = this.mcpRelayServer?.resolveResponse(
          params as unknown as McpRelayResponse,
        );
        // Logged so the desktop's response behavior is visible from the
        // readable sandbox side, not just the (often invisible) desktop logs.
        this.logger.debug("MCP relay response received", {
          requestId: String(params.requestId),
          server: String(params.server),
          resolved,
        });
        if (!resolved) {
          throw new Error(
            `No pending MCP relay request found for id: ${String(params.requestId)}`,
          );
        }
        return { resolved: true };
      }

      default:
        throw new Error(`Unknown method: ${method}`);
    }
  }

  private async initializeSession(
    payload: JwtPayload,
    sseController: SseController | null,
  ): Promise<void> {
    // Race condition guard: autoInitializeSession() starts first, but while it awaits
    // newSession() (which takes ~1-2s for MCP metadata fetch), the Temporal relay connects
    // to GET /events. That handler sees this.session === null and calls initializeSession()
    // again, creating a duplicate session that sends the same prompt twice — resulting in
    // duplicate Slack messages. This lock ensures the second caller waits for the first
    // initialization to finish and reuses the session.
    if (this.initializationPromise) {
      this.logger.debug("Waiting for in-progress initialization", {
        runId: payload.run_id,
      });
      await this.initializationPromise;
      // After waiting, just attach the SSE controller if needed
      if (this.session && sseController) {
        this.session.sseController = sseController;
        this.session.hasDesktopConnected = true;
        this.replayPendingEvents();
      }
      return;
    }

    this.bootTracker = new AgentBootTracker(payload.run_id);
    this.initializationPromise = this._doInitializeSession(
      payload,
      sseController,
    );
    const initStartedAt = Date.now();
    try {
      await this.initializationPromise;
    } catch (error) {
      this.bootTracker.markFailed();
      const telemetry = this.initializingTelemetry;
      telemetry?.append(payload.run_id, {
        type: "notification",
        timestamp: new Date().toISOString(),
        notification: {
          jsonrpc: "2.0",
          method: POSTHOG_NOTIFICATIONS.INITIALIZATION_FAILED,
          params: {
            runtimeAdapter: this.getRuntimeAdapter(),
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
      throw error;
    } finally {
      this.initializingTelemetry = undefined;
      this.initializationPromise = null;
    }
  }

  /**
   * The task's origin decides which origin-gated local tools load, so a transient failure here
   * would silently drop report_insight from an analysis run. Retry, then give up so a task that
   * genuinely does not exist still starts the session.
   */
  private async fetchTaskForSessionContext(
    taskId: string,
  ): Promise<Task | null> {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        return await this.posthogAPI.getTask(taskId);
      } catch (err) {
        if (attempt === 2) {
          this.logger.warn("Failed to fetch task for session context", {
            taskId,
            error: err,
          });
          return null;
        }
        await sleepWithBackoff(attempt, {
          initialDelayMs: 250,
          maxDelayMs: 1000,
        });
      }
    }
    return null;
  }

  private async _doInitializeSession(
    payload: JwtPayload,
    sseController: SseController | null,
  ): Promise<void> {
    if (this.session) {
      await this.cleanupSession();
    }

    this.resumeState = null;
    this.nativeResume = null;
    this.preSessionEvents = [];
    this.prewarmedRun = false;
    this.prewarmedStartupTurnPending = false;
    this.autoPublishStateResolved = false;
    this.warmReasoningEffortResolved = false;

    this.logger.debug("Initializing session", {
      runId: payload.run_id,
      taskId: payload.task_id,
    });

    const deviceInfo: DeviceInfo = {
      type: "cloud",
      name: process.env.HOSTNAME || "cloud-sandbox",
    };

    const [preTaskRun, preTask] = await this.bootTracker.measure(
      "context_fetch",
      () =>
        Promise.all([
          this.posthogAPI
            .getTaskRun(payload.task_id, payload.run_id)
            .catch((err) => {
              this.logger.debug(
                "Failed to fetch task run for session context",
                {
                  taskId: payload.task_id,
                  runId: payload.run_id,
                  error: err,
                },
              );
              return null;
            }),
          this.fetchTaskForSessionContext(payload.task_id),
        ]),
    );
    this.taskRepositories =
      preTask?.repositories ??
      (preTask?.repository ? [preTask.repository] : []);

    this.prewarmedRun = preTaskRun?.state.prewarmed === true;
    this.prewarmedStartupTurnPending = this.prewarmedRun;

    const runtimeAdapter = this.getRuntimeAdapter();

    const gatewayEnv = this.configureEnvironment({
      isInternal: preTask?.internal === true,
      originProduct: preTask?.origin_product,
      signalReportId: preTask?.signal_report,
      aiStage: getTaskRunStateString(preTaskRun, "ai_stage"),
      taskId: payload.task_id,
      taskRunId: payload.run_id,
      taskUserId: payload.user_id || preTask?.created_by?.id || null,
      taskTitle: preTask?.title,
      taskOriginKey: preTask?.origin_key,
      repositories: this.taskRepositories,
      runtimeAdapter,
      sandboxEnvironmentId: getTaskRunStateString(
        preTaskRun,
        "sandbox_environment_id",
      ),
      snapshotKind: preTaskRun
        ? (getTaskRunStateString(preTaskRun, "snapshot_kind") ?? "absent")
        : null,
      prewarmed: preTaskRun ? this.prewarmedRun : null,
      executionEnvironment: "cloud",
    });

    if (this.config.repoReadyFile && gatewayEnv.anthropicBaseUrl) {
      // Authed so this cache-warm matches the session's own authed fetch
      // (the models cache is keyed on auth presence).
      void fetchGatewayModels({
        gatewayUrl: gatewayEnv.anthropicBaseUrl,
        authToken: gatewayEnv.anthropicAuthToken,
        projectId: Number(gatewayEnv.posthogProjectId) || undefined,
      }).catch(() => {});
    }

    const prUrl = getTaskRunStateString(preTaskRun, "slack_notified_pr_url");

    // Unconditional so a re-init on the same instance drops a stale PR URL.
    this.detectedPrUrl = prUrl;

    const slackThreadUrl = getTaskRunStateString(
      preTaskRun,
      "slack_thread_url",
    );

    // Unconditional for the same reason as detectedPrUrl: a re-init on this
    // instance must not keep the previous run's delivery capability.
    this.slackArtifactDelivery = readSlackArtifactDelivery(preTaskRun);
    this.slackChartDelivery = readSlackChartDelivery(preTaskRun);

    // Web backlink to the inbox report that spawned this task, so the
    // auto-generated PR can point back at it. Built from the same pieces as the
    // report's `_posthogUrl`: <apiUrl>/project/<projectId>/inbox/<reportId>.
    const signalReportId = preTask?.signal_report;
    const inboxReportUrl = signalReportId
      ? `${this.config.apiUrl.replace(/\/$/, "")}/project/${this.config.projectId}/inbox/${signalReportId}`
      : null;

    const sessionSystemPrompt = this.buildSessionSystemPrompt(
      prUrl,
      slackThreadUrl,
      inboxReportUrl,
    );
    const codexInstructions =
      runtimeAdapter === "codex"
        ? this.buildCodexInstructions(sessionSystemPrompt)
        : undefined;

    const posthogAPI = new PostHogAPIClient({
      apiUrl: this.config.apiUrl,
      projectId: this.config.projectId,
      getApiKey: () => this.config.apiKey,
      userAgent: `posthog/cloud.hog.dev; version: ${this.config.version ?? packageJson.version}`,
    });

    const telemetry = this.createRunTelemetry(
      payload,
      deviceInfo,
      runtimeAdapter,
    );
    this.initializingTelemetry = telemetry;

    const logWriter = new SessionLogWriter({
      posthogAPI,
      logger: new Logger({ debug: true, prefix: "[SessionLogWriter]" }),
      sinks: telemetry ? [telemetry] : undefined,
    });

    const acpConnection = createAcpConnection({
      adapter: runtimeAdapter,
      taskRunId: payload.run_id,
      taskId: payload.task_id,
      deviceType: deviceInfo.type,
      logWriter,
      logger: this.logger,
      claudeGatewayEnv: runtimeAdapter !== "codex" ? gatewayEnv : undefined,
      codexOptions:
        runtimeAdapter === "codex"
          ? {
              cwd: this.config.repositoryPath ?? "/tmp/workspace",
              ...codexAuthFromGatewayEnv(gatewayEnv),
              // Bundled-binary hint for the native codex CLI: the codex
              // binary itself, or any file in its directory. Set in the
              // sandbox image (POSTHOG_CODEX_BINARY_PATH); when unset the
              // adapter uses the @openai/codex vendored binary.
              binaryPath: process.env.POSTHOG_CODEX_BINARY_PATH,
              model: this.config.model ?? DEFAULT_CODEX_MODEL,
              // Claude-only levels like ultracode must not leak into codex.
              reasoningEffort:
                this.config.reasoningEffort &&
                isSupportedReasoningEffort(
                  "codex",
                  this.config.model ?? DEFAULT_CODEX_MODEL,
                  this.config.reasoningEffort,
                )
                  ? this.config.reasoningEffort
                  : undefined,
              developerInstructions: codexInstructions,
              httpHeaders: gatewayEnv.openaiCustomHeaders,
            }
          : undefined,
      onStructuredOutput: async (output) => {
        await this.posthogAPI.setTaskRunOutput(
          payload.task_id,
          payload.run_id,
          {
            output,
          },
        );
      },
    });

    // Tap both streams to broadcast all ACP messages via SSE (mimics local transport)
    this.adapterEmittedTurnComplete = false;
    const onAcpMessage = (message: unknown) =>
      this.handleAcpTransportMessage(message);

    const tappedReadable = createTappedReadableStream(
      acpConnection.clientStreams.readable as ReadableStream<Uint8Array>,
      onAcpMessage,
      this.logger,
    );

    const tappedWritable = createTappedWritableStream(
      acpConnection.clientStreams.writable as WritableStream<Uint8Array>,
      onAcpMessage,
      this.logger,
    );

    const clientStream = ndJsonStream(tappedWritable, tappedReadable);

    const clientConnection = new ClientSideConnection(
      () => this.createCloudClient(payload),
      clientStream,
    );

    const initializeResult = await this.bootTracker.measure(
      "acp_initialize",
      () =>
        clientConnection.initialize({
          protocolVersion: PROTOCOL_VERSION,
          clientCapabilities: {},
        }),
    );
    const steering = extractSteeringCapability(initializeResult);
    const conversationClear =
      extractConversationClearCapability(initializeResult);

    const runState = preTaskRun?.state;
    // Preserve native Codex modes for cloud runs so they behave the same as
    // local sessions. Claude keeps the historical auto-approved default when
    // PostHog Desktop has not explicitly selected a mode.
    const initialPermissionMode: PermissionMode =
      typeof runState?.initial_permission_mode === "string"
        ? (runState.initial_permission_mode as PermissionMode)
        : runtimeAdapter === "codex"
          ? "auto"
          : "bypassPermissions";
    const pendingUserArtifactIds = Array.isArray(
      runState?.pending_user_artifact_ids,
    )
      ? runState.pending_user_artifact_ids.filter(
          (artifactId): artifactId is string => typeof artifactId === "string",
        )
      : [];
    const sessionCwd = this.config.repositoryPath ?? "/tmp/workspace";
    // Only a run with no repository at all gets the discover-and-clone tools;
    // a multi-repository workspace already has its repos on disk.
    const channelMode =
      !this.config.repositoryPath && this.taskRepositories.length === 0;
    const sessionMeta = {
      sessionId: payload.run_id,
      taskRunId: payload.run_id,
      taskId: payload.task_id,
      environment: "cloud",
      mode: this.getEffectiveMode(payload),
      systemPrompt: sessionSystemPrompt,
      ...(this.config.model && { model: this.config.model }),
      allowedDomains: this.config.allowedDomains,
      jsonSchema: preTask?.json_schema ?? null,
      permissionMode: initialPermissionMode,
      ...(channelMode && { channelMode: true }),
      posthogExecPermissionRegex: this.posthogExecPermissionRegexSource,
      ...(preTask?.origin_product && {
        taskOriginProduct: preTask.origin_product,
      }),
      ...(runState?.end_run_when_done === true && { endRunWhenDone: true }),
      ...(this.config.baseBranch && { baseBranch: this.config.baseBranch }),
      ...(runtimeAdapter === "claude" &&
        this.config.contextWindow && {
          contextWindow: this.config.contextWindow,
        }),
      ...(runtimeAdapter === "claude" &&
        this.config.fastMode !== undefined && {
          fastMode: this.config.fastMode,
        }),
      ...this.buildClaudeCodeSessionMeta(runtimeAdapter),
    };

    await this.bootTracker.measure("repository_ready", () =>
      this.waitForRepoReady(),
    );
    const existingPrCheckoutPromise =
      this.buildExistingPrCheckoutPromise(prUrl);
    // Overlap the best-effort PR checkout with the rest of session setup. The
    // checkout promise is always awaited in `finally` so a throw from
    // installSkillBundleArtifacts / prepareNativeResume / startMcpRelayServer
    // can never abandon an in-flight `gh pr checkout` that would keep mutating
    // the working tree after session start has been abandoned — the awaited
    // settle (plus the checkout's own abort-on-return) cancels it. The overlap
    // is safe despite both touching repositoryPath: skill bundles install under
    // `.posthog/skills/<runId>/...`, which is gitignored (untracked) in target
    // repos, so `git checkout` — which only updates tracked files — cannot
    // conflict with those writes or leave them associated with the wrong branch.
    let effectiveSessionMeta: typeof sessionMeta & {
      nativeGoal?: NonNullable<ResumeState["nativeGoal"]>;
    } = sessionMeta;
    const [nativeResume, sessionMcpServers] = await this.bootTracker.measure(
      "session_dependencies",
      async () => {
        try {
          await this.installSkillBundleArtifacts(
            payload.task_id,
            payload.run_id,
            this.getArtifactsById(
              preTaskRun?.artifacts,
              pendingUserArtifactIds,
            ),
          );
          const preparedNativeResume = await this.prepareNativeResume(
            payload,
            posthogAPI,
            preTaskRun,
            runtimeAdapter,
            sessionCwd,
            initialPermissionMode,
          );
          const preparedMcpServers: AcpMcpServer[] = toAcpMcpServers([
            ...(this.config.mcpServers ?? []),
            ...(await this.startMcpRelayServer()),
          ]);
          return [preparedNativeResume, preparedMcpServers] as const;
        } finally {
          if (existingPrCheckoutPromise) {
            this.logExistingPrCheckoutResult(
              prUrl,
              await existingPrCheckoutPromise,
            );
          }
        }
      },
    );

    const acpSessionId = await this.bootTracker.measure(
      "session_create",
      async () => {
        let sessionId: string | null = null;
        if (nativeResume) {
          try {
            await clientConnection.resumeSession({
              sessionId: nativeResume.sessionId,
              cwd: sessionCwd,
              mcpServers: sessionMcpServers,
              _meta: {
                ...effectiveSessionMeta,
                sessionId: nativeResume.sessionId,
              },
            });
            sessionId = nativeResume.sessionId;
            this.nativeResume = nativeResume;
            this.logger.debug("ACP session resumed", {
              acpSessionId: sessionId,
              runId: payload.run_id,
              warm: nativeResume.warm,
            });
          } catch (error) {
            // resumeState is still loaded, so the summary resume path takes over
            // on the fresh session below.
            this.logger.warn("Native resume failed; starting a fresh session", {
              sessionId: nativeResume.sessionId,
              error: error instanceof Error ? error.message : String(error),
            });
          }
        }
        if (!sessionId) {
          const restoredNativeGoal =
            this.getNativeGoalForFreshSession(runtimeAdapter);
          effectiveSessionMeta = restoredNativeGoal
            ? { ...sessionMeta, nativeGoal: restoredNativeGoal }
            : sessionMeta;
          const sessionResponse = await clientConnection.newSession({
            cwd: sessionCwd,
            mcpServers: sessionMcpServers,
            _meta: effectiveSessionMeta,
          });
          sessionId = sessionResponse.sessionId;
          this.logger.debug("ACP session created", {
            acpSessionId: sessionId,
            runId: payload.run_id,
          });
        }
        return sessionId;
      },
    );
    this.evaluatedPrUrls.clear();
    this.prAttributionChain = Promise.resolve();

    this.session = {
      payload,
      acpSessionId,
      acpConnection,
      clientConnection,
      sseController,
      deviceInfo,
      logWriter,
      telemetry,
      permissionMode: initialPermissionMode,
      hasDesktopConnected: sseController !== null,
      sessionMeta: effectiveSessionMeta,
    };
    this.initializingTelemetry = undefined;
    this.flushPreSessionEvents();

    this.logger = new Logger({
      debug: true,
      prefix: "[AgentServer]",
      onLog: (level, scope, message, data) => {
        this.emitConsoleLog(level, scope, message, data);
      },
    });

    this.sessionReadyBootMs = Math.round(process.uptime() * 1000);
    this.sessionInitMs = Math.max(
      0,
      Date.now() - (this.barrierReleasedAtMs ?? Date.now()),
    );
    this.bootTracker.markReady();
    this.logger.debug("Session initialized successfully", {
      bootMs: this.sessionReadyBootMs,
      sessionInitMs: this.sessionInitMs,
    });
    this.logger.debug(
      `Agent version: ${this.config.version ?? packageJson.version}`,
    );
    await logAgentshRuntimeInfo(this.logger);
    this.logger.debug(`Initial permission mode: ${initialPermissionMode}`);

    // Lifecycle handshake: clients gate "agent is ready to accept user
    // messages" on this notification. Persisted to the session log so
    // warm reconnects (sandbox restart with snapshot resume) replay it
    // and see the agent come online again.
    const runStartedNotification = {
      jsonrpc: "2.0" as const,
      method: POSTHOG_NOTIFICATIONS.RUN_STARTED,
      params: {
        sessionId: acpSessionId,
        runId: payload.run_id,
        taskId: payload.task_id,
        agentVersion: this.config.version ?? packageJson.version,
        ...(steering ? { steering } : {}),
        // Absent on older agents, which is exactly what the host gates on.
        ...(conversationClear ? { conversationClear } : {}),
      },
    };
    this.broadcastEvent({
      type: "notification",
      timestamp: new Date().toISOString(),
      notification: runStartedNotification,
    });
    this.session.logWriter.appendRawLine(
      payload.run_id,
      JSON.stringify(runStartedNotification),
    );

    // Mirror the "agent" setup step onto the ingest leg the client is reading;
    // the orchestrator's completed progress only lands in Django.
    const agentStartedProgress = {
      jsonrpc: "2.0" as const,
      method: POSTHOG_NOTIFICATIONS.PROGRESS,
      params: {
        group: `setup:${payload.run_id}`,
        step: "agent",
        status: "completed",
        label: "Started agent",
      },
    };
    this.broadcastEvent({
      type: "notification",
      timestamp: new Date().toISOString(),
      notification: agentStartedProgress,
    });
    this.session.logWriter.appendRawLine(
      payload.run_id,
      JSON.stringify(agentStartedProgress),
    );

    // Signal in_progress so the UI can start polling for updates
    this.posthogAPI
      .updateTaskRun(payload.task_id, payload.run_id, {
        status: "in_progress",
      })
      .catch((err) =>
        this.logger.debug("Failed to set task run to in_progress", err),
      );

    await this.sendInitialTaskMessage(payload, preTaskRun);
  }

  private extractErrorClassification(error: unknown): {
    classification: AgentErrorClassification;
    message: string;
  } {
    const message =
      error instanceof Error ? error.message : String(error ?? "");

    // Prefer the structured `data` carried on RequestError if present.
    const parsed = errorWithClassificationSchema.safeParse(error);
    if (parsed.success) {
      return { classification: parsed.data.data.classification, message };
    }

    return { classification: classifyAgentError(message), message };
  }

  private async runOwnedTurn<T>(operation: () => Promise<T>): Promise<T> {
    this.activeOwnedTurnCount += 1;
    try {
      return await operation();
    } finally {
      this.activeOwnedTurnCount -= 1;
    }
  }

  private async runStartupTurn<T>(operation: () => Promise<T>): Promise<T> {
    this.activeStartupTurnCount += 1;
    try {
      return await this.runOwnedTurn(operation);
    } finally {
      this.activeStartupTurnCount -= 1;
    }
  }

  private async acquireNonSteerDeliveryTurn(): Promise<() => void> {
    const previous = this.nonSteerDeliveryTail;
    let release!: () => void;
    this.nonSteerDeliveryTail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    return release;
  }

  /**
   * Send an initial/resume turn prompt, absorbing transient upstream
   * failures with a bounded number of retries. These turns run unattended
   * (no user watching who could retry), so without this a single transient
   * transport cut fails the whole run. A stream that died mid-response has
   * already delivered the original prompt into the session history, so that
   * case retries with a hidden continuation; failures where the request may
   * never have been processed re-send the original prompt instead.
   */
  private async promptWithUpstreamRetry(request: {
    sessionId: string;
    prompt: ContentBlock[];
    _meta?: Record<string, unknown>;
  }): Promise<PromptResponse> {
    let retries = 0;
    let continueInterruptedTurn = false;
    for (;;) {
      // Re-read the session on every attempt: it can be torn down or
      // replaced while the retry delay is pending.
      const session = this.session;
      if (!session) {
        throw new Error("Agent session ended before the turn could be sent");
      }
      const attempt = continueInterruptedTurn
        ? {
            sessionId: session.acpSessionId,
            prompt: [
              hiddenTextBlock(
                "The previous response was interrupted by a transient connection error. " +
                  "Continue from where you left off — do not repeat work that already completed.",
              ),
            ],
          }
        : { ...request, sessionId: session.acpSessionId };
      try {
        return await session.clientConnection.prompt(attempt);
      } catch (error) {
        const { classification, message } =
          this.extractErrorClassification(error);
        if (
          !upstreamProviderFailureClassifications.has(classification) ||
          retries >= MAX_UPSTREAM_TURN_RETRIES
        ) {
          throw error;
        }
        retries += 1;
        // Only a mid-response stream death guarantees the prompt reached the
        // model; connection/timeout/status failures re-send the original.
        continueInterruptedTurn =
          classification === "upstream_stream_terminated";
        this.logger.warn(
          "Turn hit a transient upstream failure; retrying after a short delay",
          {
            classification,
            message,
            attempt: retries,
            continueInterruptedTurn,
          },
        );
        await new Promise((resolve) =>
          setTimeout(resolve, UPSTREAM_TURN_RETRY_DELAY_MS),
        );
      }
    }
  }

  private async handleTurnFailure(
    payload: JwtPayload,
    phase: "initial" | "resume" | "followup",
    error: unknown,
  ): Promise<{ recoverable: boolean }> {
    const { classification, message } = this.extractErrorClassification(error);
    const isUpstreamFailure =
      upstreamProviderFailureClassifications.has(classification);
    const displayMessage = isUpstreamFailure
      ? UPSTREAM_PROVIDER_FAILURE_MESSAGE
      : message || "Agent error";
    const recoverable =
      isUpstreamFailure &&
      phase === "followup" &&
      this.getEffectiveMode(payload) === "interactive";
    const expectedIdleTransportClosure =
      recoverable && /^ACP connection closed$/i.test(message.trim());

    this.logger.error(`send_${phase}_task_message_failed`, {
      classification,
      message,
      recoverable,
    });

    if (!expectedIdleTransportClosure) {
      this.broadcastTurnFailure(classification, displayMessage);
    }

    if (recoverable) {
      this.broadcastTurnComplete("error_recoverable");
      return { recoverable: true };
    }

    await this.signalTaskComplete(payload, "error", displayMessage);
    return { recoverable: false };
  }

  private broadcastTurnFailure(
    classification: AgentErrorClassification,
    message: string,
  ): void {
    if (!this.session) return;
    const notification = {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        sessionId: this.session.acpSessionId,
        update: {
          sessionUpdate: "error",
          errorType: classification,
          message,
        },
      },
    };

    this.broadcastEvent({
      type: "notification",
      timestamp: new Date().toISOString(),
      notification,
    });

    this.session.logWriter.appendRawLine(
      this.session.payload.run_id,
      JSON.stringify(notification),
    );
  }

  private async sendInitialTaskMessage(
    payload: JwtPayload,
    prefetchedRun?: TaskRun | null,
  ): Promise<void> {
    if (!this.session) return;

    let taskRun = prefetchedRun ?? null;
    try {
      const refresh = await withTimeout(
        this.posthogAPI.getTaskRun(payload.task_id, payload.run_id),
        INITIAL_TASK_RUN_REFRESH_TIMEOUT_MS,
      );
      if (refresh.result === "success") taskRun = refresh.value;
    } catch (error) {
      this.logger.debug("Failed to refresh task run before initial message", {
        taskId: payload.task_id,
        runId: payload.run_id,
        error,
      });
    }

    const taskRunState = taskRun?.state as Record<string, unknown> | undefined;
    const prewarmed = taskRunState?.prewarmed === true;
    const hasPendingUserPrompt =
      (typeof taskRunState?.pending_user_message === "string" &&
        taskRunState.pending_user_message.trim().length > 0) ||
      (Array.isArray(taskRunState?.pending_user_artifact_ids) &&
        taskRunState.pending_user_artifact_ids.length > 0);

    // Load the summary fallback before deciding to idle. A prewarmed run that idles here reads
    // this state when its first message arrives, and initialization may have failed to fetch the
    // run that `prepareNativeResume` needed — leaving both resume fields empty and starting the
    // resumed task with none of its prior conversation.
    if (!this.nativeResume && !this.resumeState) {
      const resumeRunId = this.getResumeRunId(taskRun);
      if (resumeRunId) {
        await this.loadResumeState(
          payload.task_id,
          resumeRunId,
          payload.run_id,
        );
      }
    }

    // `await_user_message` is the marker the backend clears on activation. `prewarmed` is permanent
    // provenance that outlives it, so idling on that alone would strand a run whose first message
    // was already delivered — every later reinitialization would wait for a message nobody sends.
    const awaitsFirstMessage = taskRunState?.await_user_message === true;
    if (prewarmed && awaitsFirstMessage && !hasPendingUserPrompt) {
      this.prewarmedRun = true;
      this.logger.debug(
        "Prewarmed run awaits its forwarded first message, skipping initial message",
      );
      return;
    }

    if (this.nativeResume) {
      if (await this.settleIdleResume(payload, taskRun)) return;
      await this.sendResumeContinuation(payload, taskRun);
      return;
    }

    if (this.resumeState && this.resumeState.conversation.length > 0) {
      await this.sendResumeMessage(payload, taskRun);
      return;
    }

    let promptDispatched = false;
    let releaseSelfDelivery: (() => void) | undefined;
    try {
      const task = await this.posthogAPI.getTask(payload.task_id);

      const initialPromptOverride = taskRun
        ? this.getInitialPromptOverride(taskRun)
        : null;
      const pendingUserPrompt = await this.getPendingUserPrompt(taskRun);
      // A prewarmed run gets its first message forwarded as a user_message
      // signal on activation; building one from task.description here too
      // would deliver it twice (and without the forwarded artifacts).
      let initialPrompt: ContentBlock[] = [];
      let initialPromptMeta: Record<string, unknown> | undefined;
      let initialPromptMessageId: string | undefined;
      if (pendingUserPrompt?.prompt.length) {
        initialPrompt = pendingUserPrompt.prompt;
        initialPromptMeta = pendingUserPrompt.meta;
        initialPromptMessageId = pendingUserPrompt.messageId;
      } else if (initialPromptOverride) {
        initialPrompt = [{ type: "text", text: initialPromptOverride }];
      } else if (task.description && !prewarmed) {
        initialPrompt = [{ type: "text", text: task.description }];
      }

      if (initialPrompt.length === 0) {
        this.logger.debug(
          prewarmed
            ? "Prewarmed run awaits its forwarded first message, skipping initial message"
            : "Task has no description, skipping initial message",
        );
        return;
      }

      this.logger.debug("Sending initial task message", {
        taskId: payload.task_id,
        descriptionLength: promptBlocksToText(initialPrompt).length,
        usedInitialPromptOverride: !!initialPromptOverride,
        usedPendingUserMessage: !!pendingUserPrompt?.prompt.length,
      });

      this.session.logWriter.resetTurnMessages(payload.run_id);
      const acpSessionId = this.session.acpSessionId;
      if (!acpSessionId) {
        throw new Error("Agent session is missing its ACP session ID");
      }

      if (initialPromptMessageId) {
        if (
          this.deliveredMessageIds.has(initialPromptMessageId) ||
          this.inFlightMessageDeliveries.has(initialPromptMessageId)
        ) {
          this.logger.info(
            "Pending message already delivered by a forwarded command; skipping the startup prompt",
            { messageId: initialPromptMessageId },
          );
          return;
        }
        releaseSelfDelivery = this.beginSelfDelivery(initialPromptMessageId);
      }
      promptDispatched = true;

      const result = await this.runStartupTurn(() =>
        this.promptWithUpstreamRetry({
          sessionId: acpSessionId,
          prompt: initialPrompt,
          ...(initialPromptMeta ? { _meta: initialPromptMeta } : {}),
        }),
      );

      this.logger.debug("Initial task message completed", {
        stopReason: result.stopReason,
      });

      await this.clearPendingInitialPromptState(payload, taskRun);

      if (result.stopReason === "end_turn") {
        void this.syncCloudBranchMetadata(payload);
      }

      this.recordTurnUsage(result.usage);
      this.broadcastTurnComplete(result.stopReason);

      if (result.stopReason === "end_turn") {
        await this.relayAgentResponse(payload);
      }

      await this.finalizeRunTelemetry(payload);
    } catch (error) {
      this.logger.error("Failed to send initial task message", error);
      if (this.session) {
        await this.session.logWriter.flushAll();
      }
      if (promptDispatched) {
        await this.clearPendingInitialPromptState(payload, taskRun);
      }
      await this.handleTurnFailure(payload, "initial", error);
    } finally {
      releaseSelfDelivery?.();
    }
  }

  private async sendResumeMessage(
    payload: JwtPayload,
    taskRun: TaskRun | null,
  ): Promise<void> {
    if (!this.session || !this.resumeState) return;
    const resumeState = this.resumeState;
    taskRun = await this.refreshTaskRunForResume(payload, taskRun);

    await this.runResumeTurn(payload, taskRun, "Resume message", async () => {
      const conversationSummary = formatConversationForResume(
        resumeState.conversation,
      );

      const pendingUserPrompt = await this.getPendingUserPrompt(taskRun);

      let resumePromptBlocks: ContentBlock[];
      let resumePromptMeta: Record<string, unknown> | undefined;
      let resumePromptMessageId: string | undefined;
      if (pendingUserPrompt?.prompt.length) {
        resumePromptMeta = pendingUserPrompt.meta;
        resumePromptMessageId = pendingUserPrompt.messageId;
        resumePromptBlocks = [
          hiddenTextBlock(
            "You are resuming a previous conversation. Use the current workspace contents together with the preserved conversation history below.\n\n" +
              `Here is the conversation history from the previous session:\n\n` +
              `${conversationSummary}\n\n` +
              `The user has sent a new message:\n\n`,
          ),
          ...pendingUserPrompt.prompt,
          hiddenTextBlock(
            "\n\nRespond to the user's new message above. You have full context from the previous session.",
          ),
        ];
      } else {
        resumePromptBlocks = [
          hiddenTextBlock(
            "You are resuming a previous conversation. Use the current workspace contents together with the preserved conversation history below.\n\n" +
              `Here is the conversation history from the previous session:\n\n` +
              `${conversationSummary}\n\n` +
              `Continue from where you left off. The user is waiting for your response.`,
          ),
        ];
      }

      this.logger.debug("Sending resume message", {
        taskId: payload.task_id,
        conversationTurns: resumeState.conversation.length,
        promptLength: promptBlocksToText(resumePromptBlocks).length,
        hasPendingUserMessage: !!pendingUserPrompt?.prompt.length,
      });

      return {
        prompt: resumePromptBlocks,
        ...(resumePromptMeta ? { meta: resumePromptMeta } : {}),
        messageId: resumePromptMessageId,
      };
    });
  }

  private async settleIdleResume(
    payload: JwtPayload,
    taskRun: TaskRun | null,
  ): Promise<boolean> {
    if (!this.session || process.env.POSTHOG_RESUME_IDLE !== "1") return false;

    const pendingUserPrompt = await this.getPendingUserPrompt(taskRun);
    if (pendingUserPrompt?.prompt.length) return false;

    this.logger.debug("Idle resume settled without a turn", {
      taskId: payload.task_id,
      runId: payload.run_id,
      sessionId: this.nativeResume?.sessionId,
      warm: this.nativeResume?.warm,
    });

    this.resumeState = null;
    this.nativeResume = null;

    this.broadcastTurnComplete("end_turn");
    await this.session.logWriter.flushAll();
    return true;
  }

  private async preparePrewarmedResumePrompt(
    payload: JwtPayload,
    prompt: ContentBlock[],
  ): Promise<{ prompt: ContentBlock[]; consumed: boolean }> {
    if (!this.prewarmedRun) {
      return { prompt, consumed: false };
    }

    if (this.nativeResume) {
      this.logger.debug("Applying deferred native resume to user message", {
        taskId: payload.task_id,
        sessionId: this.nativeResume.sessionId,
        warm: this.nativeResume.warm,
      });
      return { prompt, consumed: true };
    }

    if (!this.resumeState?.conversation.length) {
      return { prompt, consumed: false };
    }

    const resumeState = this.resumeState;

    this.logger.debug("Applying deferred summary resume to user message", {
      taskId: payload.task_id,
      conversationTurns: resumeState.conversation.length,
    });

    return {
      prompt: this.wrapPromptWithSummaryResume(resumeState, prompt),
      consumed: true,
    };
  }

  /** Wrap the user's message in the previous session's conversation, hidden from the transcript. */
  private wrapPromptWithSummaryResume(
    resumeState: ResumeState,
    prompt: ContentBlock[],
  ): ContentBlock[] {
    const conversationSummary = formatConversationForResume(
      resumeState.conversation,
    );
    return [
      hiddenTextBlock(
        "You are resuming a previous conversation. Use the current workspace contents together with the preserved conversation history below.\n\n" +
          `Here is the conversation history from the previous session:\n\n` +
          `${conversationSummary}\n\n` +
          "The user has sent a new message:\n\n",
      ),
      ...prompt,
      hiddenTextBlock(
        "\n\nRespond to the user's new message above. You have full context from the previous session.",
      ),
    ];
  }

  /**
   * Recover a deferred native resume whose transcript overflowed the context window: open a fresh
   * session and rebuild the prompt around summarized history instead. Returns the replacement
   * prompt, or null when there is nothing to fall back to.
   *
   * `sendResumeContinuation` gets this through `runResumeTurn`'s `retryOnOversizedPrompt`, but a
   * prewarmed run defers its resume onto the first forwarded `user_message` and never goes through
   * that path — without this it would fail the run instead of retrying.
   */
  private async retryOversizedDeferredResume(
    payload: JwtPayload,
    prompt: ContentBlock[],
  ): Promise<ContentBlock[] | null> {
    if (this.oversizedResumeRetried || !this.session) {
      return null;
    }
    this.oversizedResumeRetried = true;

    const taskRun = await this.refreshTaskRunForResume(payload, null);
    const resumeRunId = this.getResumeRunId(taskRun);
    if (!resumeRunId) return null;
    if (!this.resumeState) {
      try {
        await this.loadResumeState(
          payload.task_id,
          resumeRunId,
          payload.run_id,
        );
      } catch (error) {
        this.logger.warn("Failed to reload resume state for retry", {
          error: getErrorMessage(error),
        });
        return null;
      }
    }
    const resumeState = this.resumeState;
    if (!resumeState?.conversation.length) return null;

    try {
      const response = await this.session.clientConnection.newSession({
        cwd: this.config.repositoryPath ?? "/tmp/workspace",
        mcpServers: this.config.mcpServers ?? [],
        _meta: this.session.sessionMeta,
      });
      this.session.acpSessionId = response.sessionId;
    } catch (error) {
      this.logger.warn("Failed to start fresh session for oversized resume", {
        error: getErrorMessage(error),
      });
      return null;
    }

    this.logger.warn(
      "Deferred resume prompt exceeded the context window; retrying on a fresh session with summarized history",
      { taskId: payload.task_id, runId: payload.run_id },
    );
    return this.wrapPromptWithSummaryResume(resumeState, prompt);
  }

  private async sendResumeContinuation(
    payload: JwtPayload,
    taskRun: TaskRun | null,
  ): Promise<void> {
    if (!this.session) return;
    taskRun = await this.refreshTaskRunForResume(payload, taskRun);

    await this.runResumeTurn(
      payload,
      taskRun,
      "Resume continuation",
      async () => {
        const pendingUserPrompt = await this.getPendingUserPrompt(taskRun);
        const prompt: ContentBlock[] = pendingUserPrompt?.prompt.length
          ? pendingUserPrompt.prompt
          : [
              {
                type: "text",
                text: "Continue from where you left off. The user is waiting for your response.",
              },
            ];
        this.logger.debug("Sending resume continuation", {
          taskId: payload.task_id,
          sessionId: this.nativeResume?.sessionId,
          warm: this.nativeResume?.warm,
          hasPendingUserMessage: !!pendingUserPrompt?.prompt.length,
        });

        return {
          prompt,
          ...(pendingUserPrompt?.meta ? { meta: pendingUserPrompt.meta } : {}),
          messageId: pendingUserPrompt?.messageId,
        };
      },
      { retryOnOversizedPrompt: true },
    );
  }

  private async refreshTaskRunForResume(
    payload: JwtPayload,
    fallback: TaskRun | null,
  ): Promise<TaskRun | null> {
    try {
      return await this.posthogAPI.getTaskRun(payload.task_id, payload.run_id);
    } catch (error) {
      this.logger.debug("Failed to refresh task run before resume", {
        taskId: payload.task_id,
        runId: payload.run_id,
        error,
      });
      return fallback;
    }
  }

  /**
   * A native resume replays the prior transcript verbatim; when that
   * transcript no longer fits the context window, every request (including
   * auto-compaction) is rejected, so the only way forward is a fresh session
   * seeded with the summarized history the non-native resume path uses.
   */
  private async retryOversizedResumeOnFreshSession(
    payload: JwtPayload,
    taskRun: TaskRun | null,
  ): Promise<boolean> {
    if (this.oversizedResumeRetried || !this.session) {
      return false;
    }
    this.oversizedResumeRetried = true;

    const resumeRunId = this.getResumeRunId(taskRun);
    if (!resumeRunId) return false;
    if (!this.resumeState) {
      try {
        await this.loadResumeState(
          payload.task_id,
          resumeRunId,
          payload.run_id,
        );
      } catch (error) {
        this.logger.warn("Failed to reload resume state for retry", {
          error: getErrorMessage(error),
        });
        return false;
      }
    }
    if (!this.resumeState?.conversation.length) return false;

    this.logger.warn(
      "Resume prompt exceeded the context window; retrying on a fresh session with summarized history",
      { taskId: payload.task_id, runId: payload.run_id },
    );

    try {
      const response = await this.session.clientConnection.newSession({
        cwd: this.config.repositoryPath ?? "/tmp/workspace",
        mcpServers: toAcpMcpServers(this.config.mcpServers ?? []),
        _meta: this.session.sessionMeta,
      });
      this.session.acpSessionId = response.sessionId;
    } catch (error) {
      this.logger.warn("Failed to start fresh session for oversized resume", {
        error: getErrorMessage(error),
      });
      return false;
    }

    try {
      await this.sendResumeMessage(payload, taskRun);
      return true;
    } finally {
      this.resumeState = null;
      this.nativeResume = null;
    }
  }

  private async runResumeTurn(
    payload: JwtPayload,
    taskRun: TaskRun | null,
    logLabel: string,
    buildPrompt: () => Promise<BuiltPrompt>,
    opts: { retryOnOversizedPrompt?: boolean } = {},
  ): Promise<void> {
    if (!this.session) return;

    let promptDispatched = false;
    let releaseSelfDelivery: (() => void) | undefined;
    try {
      const builtPrompt = await buildPrompt();

      this.session.logWriter.resetTurnMessages(payload.run_id);
      const acpSessionId = this.session.acpSessionId;
      if (!acpSessionId) {
        throw new Error("Agent session is missing its ACP session ID");
      }

      if (builtPrompt.messageId) {
        releaseSelfDelivery = this.beginSelfDelivery(builtPrompt.messageId);
      }
      promptDispatched = true;

      const result = await this.runStartupTurn(() =>
        this.promptWithUpstreamRetry({
          sessionId: acpSessionId,
          prompt: builtPrompt.prompt,
          ...(builtPrompt.meta ? { _meta: builtPrompt.meta } : {}),
        }),
      );

      this.logger.debug(`${logLabel} completed`, {
        stopReason: result.stopReason,
      });

      // Kept until the turn succeeds so a prompt-too-long retry can reuse it.
      this.resumeState = null;
      this.nativeResume = null;

      await this.clearPendingInitialPromptState(payload, taskRun);

      if (result.stopReason === "end_turn") {
        void this.syncCloudBranchMetadata(payload);
      }

      this.recordTurnUsage(result.usage);
      this.broadcastTurnComplete(result.stopReason);

      if (result.stopReason === "end_turn") {
        await this.relayAgentResponse(payload);
      }

      await this.finalizeRunTelemetry(payload);
    } catch (error) {
      this.logger.error(`Failed to send ${logLabel.toLowerCase()}`, error);
      if (this.session) {
        await this.session.logWriter.flushAll();
      }
      if (
        opts.retryOnOversizedPrompt &&
        isPromptTooLongError(error) &&
        (await this.retryOversizedResumeOnFreshSession(payload, taskRun))
      ) {
        return;
      }
      if (promptDispatched) {
        await this.clearPendingInitialPromptState(payload, taskRun);
      }
      await this.handleTurnFailure(payload, "resume", error);
    } finally {
      releaseSelfDelivery?.();
    }
  }

  private getInitialPromptOverride(taskRun: TaskRun): string | null {
    const override = taskRun.state.initial_prompt_override;
    return typeof override === "string" ? override.trim() || null : null;
  }

  private markMessageDelivered(messageId: string): void {
    this.deliveredMessageIds.add(messageId);
    if (this.deliveredMessageIds.size > 500) {
      const oldest = this.deliveredMessageIds.values().next().value;
      if (oldest !== undefined) {
        this.deliveredMessageIds.delete(oldest);
        this.pendingCompactContinuationMessageIds.delete(oldest);
      }
    }
  }

  private async getPendingUserPrompt(
    taskRun: TaskRun | null,
  ): Promise<BuiltPrompt | null> {
    if (!taskRun) return null;
    const state = taskRun.state;
    const message = state.pending_user_message;
    const pendingMessageId =
      typeof state.pending_user_message_id === "string" &&
      state.pending_user_message_id
        ? state.pending_user_message_id
        : undefined;
    const artifactIds = Array.isArray(state.pending_user_artifact_ids)
      ? state.pending_user_artifact_ids.filter(
          (artifactId): artifactId is string =>
            typeof artifactId === "string" && artifactId.trim().length > 0,
        )
      : [];

    // The run's artifact manifest can momentarily lag the pending-artifact ids
    // when a run starts right after the attachments were uploaded. If we were
    // asked for artifacts the manifest doesn't list yet, poll the run with a
    // short backoff so a transient gap doesn't drop the attachment and send the
    // agent the bare "Attached files: …" description instead of the file it was
    // promised.
    let manifest = taskRun.artifacts ?? [];
    let resolvedArtifacts = this.getArtifactsById(manifest, artifactIds, {
      warnOnMissing: false,
    });
    if (
      artifactIds.length > 0 &&
      resolvedArtifacts.length < artifactIds.length
    ) {
      manifest =
        (await this.resolvePendingArtifactManifest(
          taskRun,
          artifactIds,
          manifest,
        )) ?? manifest;
      resolvedArtifacts = this.getArtifactsById(manifest, artifactIds);
    }

    const prompt = await this.buildPromptFromContentAndArtifacts({
      content: typeof message === "string" ? message : undefined,
      artifacts: resolvedArtifacts,
      taskId: taskRun.task,
      runId: taskRun.id,
    });

    // Skill bundles are installed silently, so only non-skill attachments are
    // expected to surface as content (hydrated into resource_link blocks). Ids
    // the manifest still can't account for are treated as attachments, not
    // skills — better to over-warn than to silently mislead. `message` here is
    // plain text, so every resource_link block is a hydrated attachment.
    const expectedAttachmentCount = artifactIds.filter((artifactId) => {
      const known = manifest.find((artifact) => artifact.id === artifactId);
      return known ? known.type !== "skill_bundle" : true;
    }).length;
    const hydratedAttachmentCount = prompt.prompt.filter(
      (block) => block.type === "resource_link",
    ).length;
    const lostAttachmentCount =
      expectedAttachmentCount - hydratedAttachmentCount;

    if (lostAttachmentCount > 0) {
      this.logger.warn("Pending user attachments could not be loaded", {
        taskId: taskRun.task,
        runId: taskRun.id,
        requestedArtifactCount: artifactIds.length,
        expectedAttachmentCount,
        hydratedAttachmentCount,
        lostAttachmentCount,
      });
      prompt.prompt.push({
        type: "text",
        text: buildMissingAttachmentNotice(lostAttachmentCount),
      });
    }

    this.logger.debug("Built pending user prompt", {
      hasMessage: typeof message === "string" && message.trim().length > 0,
      requestedArtifactCount: artifactIds.length,
      hydratedAttachmentCount,
      lostAttachmentCount,
      blockTypes: prompt.prompt.map((block) => block.type),
    });
    if (prompt.prompt.length === 0) {
      return null;
    }
    return { ...prompt, messageId: pendingMessageId };
  }

  private async resolvePendingArtifactManifest(
    taskRun: TaskRun,
    artifactIds: string[],
    initialManifest: TaskRunArtifact[],
  ): Promise<TaskRunArtifact[] | null> {
    let latestManifest = initialManifest;

    for (let attempt = 1; attempt <= PENDING_ARTIFACT_MAX_ATTEMPTS; attempt++) {
      const refreshed = await this.refetchRunArtifacts(taskRun);
      if (refreshed) {
        const mergedManifest = [...latestManifest];
        for (const artifact of refreshed) {
          const existingIndex = mergedManifest.findIndex(
            (existing) =>
              (artifact.id && existing.id === artifact.id) ||
              (artifact.storage_path &&
                existing.storage_path === artifact.storage_path),
          );
          if (existingIndex >= 0) {
            mergedManifest[existingIndex] = artifact;
          } else {
            mergedManifest.push(artifact);
          }
        }
        latestManifest = mergedManifest;
        const resolvedArtifacts = this.getArtifactsById(
          latestManifest,
          artifactIds,
          { warnOnMissing: false },
        );
        if (resolvedArtifacts.length === artifactIds.length) {
          return latestManifest;
        }
      }

      if (attempt < PENDING_ARTIFACT_MAX_ATTEMPTS) {
        await sleep(PENDING_ARTIFACT_RETRY_DELAY_MS * attempt);
      }
    }

    return latestManifest.length > 0 ? latestManifest : null;
  }

  // Best-effort refetch of a run's artifact manifest. Returns null on any error
  // so the caller can fall back to the manifest it already has.
  private async refetchRunArtifacts(
    taskRun: TaskRun,
  ): Promise<TaskRunArtifact[] | null> {
    try {
      const refreshed = await this.posthogAPI.getTaskRun(
        taskRun.task,
        taskRun.id,
      );
      return refreshed.artifacts ?? null;
    } catch (error) {
      this.logger.debug("Failed to refetch run artifacts for pending prompt", {
        taskId: taskRun.task,
        runId: taskRun.id,
        error,
      });
      return null;
    }
  }

  private getClearedPendingUserState(taskRun: TaskRun | null): string[] | null {
    const state = taskRun?.state;
    if (!state) {
      return null;
    }

    const pendingKeys = [
      "pending_user_message",
      "pending_user_artifact_ids",
      "pending_user_message_id",
      "pending_user_message_ts",
    ].filter((key) => key in state);

    return pendingKeys.length > 0 ? pendingKeys : null;
  }

  private async clearPendingInitialPromptState(
    payload: JwtPayload,
    taskRun: TaskRun | null,
  ): Promise<void> {
    const stateRemoveKeys = this.getClearedPendingUserState(taskRun);
    if (!stateRemoveKeys) {
      return;
    }

    try {
      await this.posthogAPI.updateTaskRun(payload.task_id, payload.run_id, {
        state_remove_keys: stateRemoveKeys,
      });
    } catch (error) {
      this.logger.warn("Failed to clear pending prompt state", {
        taskId: payload.task_id,
        runId: payload.run_id,
        error: getErrorMessage(error),
      });
    }
  }

  private beginSelfDelivery(messageId: string): () => void {
    this.markMessageDelivered(messageId);
    let release: () => void = () => {};
    const outcome = new Promise<unknown>((resolve) => {
      release = () => {
        this.inFlightMessageDeliveries.delete(messageId);
        resolve({ stopReason: "duplicate_delivery", duplicate: true });
      };
    });
    void outcome.catch(() => {});
    this.inFlightMessageDeliveries.set(messageId, outcome);
    return release;
  }

  private async buildPromptFromContentAndArtifacts({
    content,
    artifacts,
    taskId,
    runId,
  }: {
    content?: string | ContentBlock[];
    artifacts?: TaskRunArtifact[];
    taskId: string;
    runId: string;
  }): Promise<BuiltPrompt> {
    const contentBlocks = content ? normalizeCloudPromptContent(content) : [];
    await this.installSkillBundleArtifacts(taskId, runId, artifacts ?? []);
    const localSkillContext = this.buildInstalledSkillPromptContext(
      contentBlocks,
      runId,
      artifacts ?? [],
    );
    const artifactBlocks = await this.hydrateArtifactsToPrompt(
      taskId,
      runId,
      (artifacts ?? []).filter((artifact) => artifact.type !== "skill_bundle"),
    );

    return {
      prompt: [...contentBlocks, ...artifactBlocks],
      ...(localSkillContext
        ? {
            meta: {
              localSkillContext: localSkillContext.context,
              ...(localSkillContext.skillName
                ? { localSkillName: localSkillContext.skillName }
                : {}),
            } satisfies Record<string, unknown>,
          }
        : {}),
    };
  }

  private getArtifactsById(
    artifacts: TaskRunArtifact[] | undefined,
    artifactIds: string[],
    // The speculative pre-refetch resolve passes false: a miss there is expected
    // (it's what triggers the refetch), so warning would be premature and would
    // double up with the post-refetch warning for a genuinely missing artifact.
    { warnOnMissing = true }: { warnOnMissing?: boolean } = {},
  ): TaskRunArtifact[] {
    if (!artifacts?.length || artifactIds.length === 0) {
      return [];
    }

    const artifactsById = new Map(
      artifacts
        .filter(
          (artifact): artifact is TaskRunArtifact & { id: string } =>
            typeof artifact.id === "string" && artifact.id.trim().length > 0,
        )
        .map((artifact) => [artifact.id, artifact]),
    );

    return artifactIds.flatMap((artifactId) => {
      const artifact = artifactsById.get(artifactId);
      if (!artifact) {
        if (warnOnMissing) {
          this.logger.warn("Pending artifact missing from run manifest", {
            artifactId,
          });
        }
        return [];
      }

      return [artifact];
    });
  }

  private async hydrateArtifactsToPrompt(
    taskId: string,
    runId: string,
    artifacts: TaskRunArtifact[],
  ): Promise<ContentBlock[]> {
    if (artifacts.length === 0) {
      return [];
    }

    this.logger.debug("Hydrating prompt artifacts", {
      taskId,
      runId,
      artifactCount: artifacts.length,
      artifactNames: artifacts.map((artifact) => artifact.name),
    });

    return (
      await Promise.all(
        artifacts.map((artifact) =>
          this.hydrateArtifactToPromptBlock(taskId, runId, artifact),
        ),
      )
    ).flatMap((artifactBlock) => (artifactBlock ? [artifactBlock] : []));
  }

  private async installSkillBundleArtifacts(
    taskId: string,
    runId: string,
    artifacts: TaskRunArtifact[],
  ): Promise<void> {
    const skillBundleArtifacts = artifacts.filter(
      (artifact) => artifact.type === "skill_bundle",
    );
    if (skillBundleArtifacts.length === 0) {
      return;
    }

    this.logger.debug("Installing skill bundle artifacts", {
      taskId,
      runId,
      artifactCount: skillBundleArtifacts.length,
      artifactNames: skillBundleArtifacts.map((artifact) => artifact.name),
    });

    for (const artifact of skillBundleArtifacts) {
      await this.installSkillBundleArtifact(taskId, runId, artifact);
    }
  }

  private buildInstalledSkillPromptContext(
    contentBlocks: ContentBlock[],
    runId: string,
    artifacts: TaskRunArtifact[],
  ): LocalSkillPromptContext | null {
    if (contentBlocks.length === 0) {
      return null;
    }

    const textBlockIndex = contentBlocks.findIndex(
      (block): block is Extract<ContentBlock, { type: "text" }> =>
        block.type === "text" && block.text.trim().length > 0,
    );
    const textBlock =
      textBlockIndex === -1 ? null : contentBlocks[textBlockIndex];
    const invocation =
      textBlock?.type === "text"
        ? this.parseLocalSkillInvocation(textBlock.text)
        : null;

    if (invocation) {
      const hasMatchingArtifact = artifacts.some(
        (artifact) =>
          artifact.type === "skill_bundle" &&
          isSkillBundleArtifactMetadata(artifact.metadata) &&
          artifact.metadata.skill_name === invocation.skillName,
      );
      const installedSkill = hasMatchingArtifact
        ? this.installedSkillBundleInfo.get(
            this.getInstalledSkillBundleInfoKey(runId, invocation.skillName),
          )
        : undefined;
      if (installedSkill) {
        return {
          skillName: invocation.skillName,
          context: this.buildInstalledSkillPrompt(
            installedSkill,
            invocation.args,
            this.getCoInstalledSkillBundles(runId, invocation.skillName),
          ),
        };
      }
    }

    const messageText = contentBlocks
      .filter(
        (block): block is Extract<ContentBlock, { type: "text" }> =>
          block.type === "text",
      )
      .map((block) => block.text)
      .join("\n");
    return this.buildAttachedSkillsPromptContext(runId, artifacts, messageText);
  }

  /**
   * Fallback for messages that install skill bundles without being a bare
   * `/skill` invocation: a running session can't discover mid-session
   * installs, so skills named in the message get their definition inlined
   * and the rest are listed with their paths.
   */
  private buildAttachedSkillsPromptContext(
    runId: string,
    artifacts: TaskRunArtifact[],
    messageText: string,
  ): LocalSkillPromptContext | null {
    const installed = artifacts
      .filter(
        (artifact) =>
          artifact.type === "skill_bundle" &&
          isSkillBundleArtifactMetadata(artifact.metadata),
      )
      .map((artifact) =>
        isSkillBundleArtifactMetadata(artifact.metadata)
          ? artifact.metadata.skill_name
          : null,
      )
      .filter((name): name is string => typeof name === "string")
      .map((name) =>
        this.installedSkillBundleInfo.get(
          this.getInstalledSkillBundleInfoKey(runId, name),
        ),
      )
      .filter((skill): skill is InstalledSkillBundle => !!skill);
    if (installed.length === 0) {
      return null;
    }

    const mentioned = installed.filter((skill) => {
      // token-boundary match so "/foo" never matches inside "/foobar"
      const escaped = skill.skillName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return new RegExp(
        `(^|[\\s(\`"'\\[])/${escaped}(?![A-Za-z0-9_/-])`,
        "m",
      ).test(messageText);
    });
    const unmentioned = installed.filter((skill) => !mentioned.includes(skill));

    const sections: string[] = [
      "The user's message references local skills that are now installed for this run. Apply a skill's instructions when the message calls for it.",
    ];
    for (const skill of mentioned) {
      sections.push(
        "",
        `--- BEGIN LOCAL SKILL ${skill.skillName} ---`,
        skill.skillDefinition.trim(),
        `--- END LOCAL SKILL ${skill.skillName} ---`,
        `Installed skill path: ${skill.skillRoot}`,
      );
    }
    if (unmentioned.length > 0) {
      sections.push(
        "",
        "Other local skills installed for this run (read a skill's SKILL.md from its path when referenced):",
        ...unmentioned.map(
          (skill) => `- /${skill.skillName}: ${skill.skillRoot}`,
        ),
      );
    }
    return { context: sections.join("\n") };
  }

  /**
   * Other skills already installed for this run (auto-bundled dependencies,
   * skills from earlier messages), listed so the model can find them by path.
   */
  private getCoInstalledSkillBundles(
    runId: string,
    invokedSkillName: string,
  ): InstalledSkillBundle[] {
    const prefix = `${runId}:`;
    return [...this.installedSkillBundleInfo.entries()]
      .filter(
        ([key, skill]) =>
          key.startsWith(prefix) && skill.skillName !== invokedSkillName,
      )
      .map(([, skill]) => skill)
      .sort((a, b) => a.skillName.localeCompare(b.skillName));
  }

  private parseLocalSkillInvocation(
    textValue: string,
  ): { skillName: string; args?: string } | null {
    const trimmed = textValue.trim();
    const match = trimmed.match(/^\/([^\s]+)(?:\s+([\s\S]*))?$/);
    if (!match?.[1]) {
      return null;
    }

    return {
      skillName: match[1],
      ...(match[2]?.trim() ? { args: match[2].trim() } : {}),
    };
  }

  private buildInstalledSkillPrompt(
    skill: InstalledSkillBundle,
    args: string | undefined,
    coInstalledSkills: InstalledSkillBundle[] = [],
  ): string {
    return [
      `The user invoked the local skill "/${skill.skillName}". Apply these skill instructions for this turn.`,
      "",
      `--- BEGIN LOCAL SKILL ${skill.skillName} ---`,
      skill.skillDefinition.trim(),
      `--- END LOCAL SKILL ${skill.skillName} ---`,
      "",
      `Installed skill path: ${skill.skillRoot}`,
      ...(coInstalledSkills.length > 0
        ? [
            "",
            "Other local skills installed for this run (when the skill above references one of these, read its SKILL.md from the listed path):",
            ...coInstalledSkills.map(
              (coInstalled) =>
                `- /${coInstalled.skillName}: ${coInstalled.skillRoot}`,
            ),
          ]
        : []),
      "",
      "User request:",
      args?.trim() || `Run /${skill.skillName}.`,
    ].join("\n");
  }

  private getInstalledSkillBundleInfoKey(
    runId: string,
    skillName: string,
  ): string {
    return `${runId}:${skillName}`;
  }

  private async installSkillBundleArtifact(
    taskId: string,
    runId: string,
    artifact: TaskRunArtifact,
  ): Promise<void> {
    const metadata = artifact.metadata;
    if (!artifact.storage_path || !isSkillBundleArtifactMetadata(metadata)) {
      throw new Error(
        `Skill bundle artifact ${artifact.name} is missing metadata`,
      );
    }

    const skillName = metadata.skill_name;
    const expectedSha256 = metadata.content_sha256;
    const installKey = `${runId}:${expectedSha256}:${skillName}`;
    if (
      this.installedSkillBundles.has(installKey) &&
      this.installedSkillBundleInfo.has(
        this.getInstalledSkillBundleInfoKey(runId, skillName),
      )
    ) {
      return;
    }

    const inFlight = this.installingSkillBundles.get(installKey);
    if (inFlight) {
      return inFlight;
    }

    const installPromise = this.performSkillBundleInstall(
      taskId,
      runId,
      artifact,
      artifact.storage_path,
      installKey,
      skillName,
      expectedSha256,
    );
    this.installingSkillBundles.set(installKey, installPromise);
    try {
      await installPromise;
    } finally {
      this.installingSkillBundles.delete(installKey);
    }
  }

  private async performSkillBundleInstall(
    taskId: string,
    runId: string,
    artifact: TaskRunArtifact,
    storagePath: string,
    installKey: string,
    skillName: string,
    expectedSha256: string,
  ): Promise<void> {
    const data = await this.posthogAPI.downloadArtifact(
      taskId,
      runId,
      storagePath,
    );
    if (!data) {
      throw new Error(`Failed to download skill bundle ${artifact.name}`);
    }

    const buffer = Buffer.from(data);
    const actualSha256 = createHash("sha256").update(buffer).digest("hex");
    if (actualSha256 !== expectedSha256) {
      throw new Error(`Skill bundle ${skillName} failed checksum validation`);
    }

    const safeSkillName = this.getSafeArtifactName(skillName);
    const skillRoot = join(
      this.config.repositoryPath ?? "/tmp/workspace",
      ".posthog",
      "skills",
      runId,
      actualSha256,
      safeSkillName,
    );

    await rm(skillRoot, { recursive: true, force: true });
    await mkdir(skillRoot, { recursive: true });
    await this.extractSkillBundle(buffer, skillRoot);

    const skillDefinition = await readFile(
      join(skillRoot, "SKILL.md"),
      "utf-8",
    ).catch(() => null);
    if (!skillDefinition?.trim()) {
      throw new Error(`Skill bundle ${skillName} does not contain SKILL.md`);
    }

    const copyFailures: Array<{ destination: string; error: unknown }> = [];
    await Promise.all(
      this.getSkillInstallDirectories(safeSkillName).map(
        async (destination) => {
          try {
            await rm(destination, { recursive: true, force: true });
            await mkdir(dirname(destination), { recursive: true });
            await cp(skillRoot, destination, { recursive: true });
          } catch (error) {
            copyFailures.push({ destination, error });
          }
        },
      ),
    );
    if (copyFailures.length > 0) {
      this.logger.warn("Failed to copy skill bundle to some skill roots", {
        taskId,
        runId,
        skillName,
        failedDestinations: copyFailures.map((failure) => failure.destination),
      });
    }

    this.installedSkillBundles.add(installKey);
    this.installedSkillBundleInfo.set(
      this.getInstalledSkillBundleInfoKey(runId, skillName),
      {
        skillName,
        skillDefinition,
        contentSha256: actualSha256,
        skillRoot,
      },
    );
    this.logger.debug("Installed skill bundle artifact", {
      taskId,
      runId,
      skillName,
      contentSha256: actualSha256,
    });
  }

  private async extractSkillBundle(
    archive: Uint8Array,
    destinationRoot: string,
  ): Promise<void> {
    const entries = unzipSync(archive);
    for (const [entryName, content] of Object.entries(entries)) {
      const normalizedEntryName = entryName.replaceAll("\\", "/");
      if (
        !normalizedEntryName ||
        normalizedEntryName.endsWith("/") ||
        normalizedEntryName.startsWith("/") ||
        normalizedEntryName.split("/").includes("..")
      ) {
        continue;
      }
      // Bundles from clients that predate export-side filtering can still
      // carry ignored entries; drop them so the sandbox skill matches what
      // current clients would have uploaded.
      if (isIgnoredSkillPath(normalizedEntryName)) {
        continue;
      }

      const destinationPath = join(destinationRoot, normalizedEntryName);
      const relativeDestination = relative(destinationRoot, destinationPath);
      if (
        !relativeDestination ||
        relativeDestination.startsWith("..") ||
        isAbsolute(relativeDestination)
      ) {
        continue;
      }

      await mkdir(dirname(destinationPath), { recursive: true });
      await writeFile(destinationPath, Buffer.from(content));
    }
  }

  private getSkillInstallDirectories(skillName: string): string[] {
    const home = process.env.HOME ?? "/tmp";
    return [
      join("/scripts", "plugins", "posthog", "skills", skillName),
      join(home, ".agents", "skills", skillName),
      join(home, ".claude", "skills", skillName),
    ];
  }

  private async hydrateArtifactToPromptBlock(
    taskId: string,
    runId: string,
    artifact: TaskRunArtifact,
  ): Promise<ContentBlock | null> {
    if (!artifact.storage_path) {
      this.logger.warn("Skipping artifact without storage path", {
        taskId,
        runId,
        artifactName: artifact.name,
      });
      return null;
    }

    const data = await this.posthogAPI.downloadArtifact(
      taskId,
      runId,
      artifact.storage_path,
    );
    if (!data) {
      throw new Error(`Failed to download artifact ${artifact.name}`);
    }

    const safeName = this.getSafeArtifactName(artifact.name);
    const artifactDir = join(
      this.config.repositoryPath ?? "/tmp/workspace",
      ".posthog",
      "attachments",
      runId,
      artifact.id ?? safeName,
    );
    await mkdir(artifactDir, { recursive: true });

    const artifactPath = join(artifactDir, safeName);
    await writeFile(artifactPath, Buffer.from(data));

    return resourceLink(pathToFileURL(artifactPath).toString(), artifact.name, {
      ...(artifact.content_type ? { mimeType: artifact.content_type } : {}),
      ...(typeof artifact.size === "number" ? { size: artifact.size } : {}),
    });
  }

  private getSafeArtifactName(name: string): string {
    const baseName = basename(name).trim();
    const normalizedName = baseName.replace(/[^\w.-]/g, "_");
    if (normalizedName.length === 0 || /^\.+$/.test(normalizedName)) {
      return "attachment";
    }
    return normalizedName;
  }

  private async waitForRepoReady(): Promise<void> {
    const readyFile = this.config.repoReadyFile;
    if (!readyFile) {
      this.barrierReleasedAtMs = Date.now();
      return;
    }

    const REPO_READY_TIMEOUT_MS = 5 * 60_000;
    const result = await waitForFile(readyFile, {
      timeoutMs: REPO_READY_TIMEOUT_MS,
      onError: (error) => {
        this.logger.debug("Repo-ready barrier check failed", {
          readyFile,
          code: error.code,
          message: error.message,
        });
      },
    });
    this.barrierReleasedAtMs = Date.now();
    if (result.timedOut) {
      this.logger.warn("Repo-ready barrier timed out; proceeding", {
        readyFile,
        waitedMs: result.waitedMs,
      });
      return;
    }
    this.logger.debug("Repo-ready barrier released", {
      readyFile,
      waitedMs: result.waitedMs,
    });
  }

  private async autoInitializeSession(): Promise<void> {
    const { taskId, runId, mode, projectId } = this.config;

    this.logger.debug("Auto-initializing session", { taskId, runId, mode });

    const resumeRunId = process.env.POSTHOG_RESUME_RUN_ID;
    if (resumeRunId) {
      await this.loadResumeState(taskId, resumeRunId, runId);
    }

    // Create a synthetic payload from config (no JWT needed for auto-init)
    const payload: JwtPayload = {
      task_id: taskId,
      run_id: runId,
      team_id: projectId,
      user_id: 0, // System-initiated
      distinct_id: "agent-server",
      mode,
    };

    await this.initializeSession(payload, null);
  }

  private getResumeRunId(taskRun: TaskRun | null): string | null {
    // Env var takes precedence (set by backend infra)
    const envRunId = process.env.POSTHOG_RESUME_RUN_ID;
    if (envRunId) return envRunId;

    // Fallback: read from TaskRun state (set by API when creating the run)
    if (!taskRun) return null;
    const stateRunId = taskRun.state.resume_from_run_id;
    return typeof stateRunId === "string" ? stateRunId.trim() || null : null;
  }

  private buildSessionSystemPrompt(
    prUrl?: string | null,
    slackThreadUrl?: string | null,
    inboxReportUrl?: string | null,
  ): string | { append: string } {
    const cloudAppend = this.buildCloudSystemPrompt(
      prUrl,
      slackThreadUrl,
      inboxReportUrl,
    );
    const userPrompt = this.config.claudeCode?.systemPrompt;

    return buildCloudSessionSystemPrompt(cloudAppend, userPrompt);
  }

  private buildCodexInstructions(
    systemPrompt: string | { append: string },
  ): string {
    const instructions =
      typeof systemPrompt === "string" ? systemPrompt : systemPrompt.append;
    // Codex has no command-rewrite hook (see rtk-guidance.ts), so RTK is
    // adopted through the developer instructions instead.
    return appendRtkGuidanceForCodex(instructions);
  }

  /**
   * Builds the optional `claudeCode` session meta. Reasoning effort and plugins
   * are independent: effort must reach Claude even when no plugins are set, so
   * it cannot sit behind a plugins guard.
   */
  private buildClaudeCodeSessionMeta(
    runtimeAdapter: Adapter,
  ): { claudeCode: { options: Record<string, unknown> } } | undefined {
    const plugins = this.config.claudeCode?.plugins;
    const effort =
      runtimeAdapter === "claude" ? this.config.reasoningEffort : undefined;

    if (!plugins?.length && !effort) {
      return undefined;
    }

    const options: Record<string, unknown> = {};
    if (plugins?.length) {
      options.plugins = plugins;
    }
    if (effort) {
      options.effort = effort;
    }
    return { claudeCode: { options } };
  }

  private getCloudInteractionOrigin(): string | undefined {
    return (
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN ??
      process.env.CODE_INTERACTION_ORIGIN ??
      process.env.TWIG_INTERACTION_ORIGIN
    );
  }

  /**
   * Automated, PostHog-branded origins: the Slack app and the Self-driving
   * inbox. These both auto-publish by default and attribute their PRs to
   * "PostHog" rather than the PostHog Desktop app.
   */
  private isAutomatedOrigin(): boolean {
    const origin = this.getCloudInteractionOrigin();
    return origin === "slack" || origin === "signal_report";
  }

  /**
   * Automated-origin cloud runs auto-publish by default, and manual runs
   * auto-publish when the user opted in (Settings → Advanced, sent as
   * autoPublish). Every other run is review-first unless the user explicitly
   * asks, and createPr=false always disables publishing.
   */
  private shouldAutoPublishCloudChanges(): boolean {
    return (
      (this.isAutomatedOrigin() || this.config.autoPublish === true) &&
      this.config.createPr !== false
    );
  }

  /** Apply settings from run state before the first turn when launch config is incomplete. */
  private async resolveActivationSettings(): Promise<string | null> {
    if (!this.session) {
      return null;
    }

    const shouldResolveReasoning =
      this.prewarmedRun && !this.warmReasoningEffortResolved;
    const shouldResolveAutoPublish =
      !this.autoPublishStateResolved &&
      this.config.autoPublish !== true &&
      this.config.createPr !== false &&
      !this.isAutomatedOrigin();
    if (!shouldResolveReasoning && !shouldResolveAutoPublish) {
      return null;
    }

    let state: TaskRunState | undefined;
    try {
      const run = await this.posthogAPI.getTaskRun(
        this.session.payload.task_id,
        this.session.payload.run_id,
      );
      state = run?.state;
    } catch (error) {
      // Keep the settings unresolved so a later message retries. A transient
      // control-plane failure must not prevent the first prompt from running.
      this.logger.debug("Failed to fetch activation settings", { error });
      return null;
    }

    if (shouldResolveReasoning) {
      await this.resolveWarmReasoningEffort(state);
    }
    return this.resolveAutoPublishFromState(state);
  }

  private async resolveWarmReasoningEffort(
    state: TaskRunState | undefined,
  ): Promise<void> {
    if (this.warmReasoningEffortResolved || !this.session) {
      return;
    }

    const reasoningEffort = state?.reasoning_effort;
    if (typeof reasoningEffort === "string" && reasoningEffort.length > 0) {
      try {
        await this.session.clientConnection.setSessionConfigOption({
          sessionId: this.session.acpSessionId,
          configId: "effort",
          value: reasoningEffort,
        });
      } catch (error) {
        // Keep this unresolved so a later message retries, but continue with
        // the effort used to start the warm session for the current prompt.
        this.logger.warn("Failed to apply warm activation reasoning effort", {
          error,
          reasoningEffort,
        });
        return;
      }
      this.config.reasoningEffort =
        reasoningEffort as AgentServerConfig["reasoningEffort"];
      this.logger.debug("Applied warm activation reasoning effort", {
        reasoningEffort,
      });
    }
    this.warmReasoningEffortResolved = true;
  }

  /**
   * The backend persists auto-publish in run state. Recover it when an older or
   * incomplete launch path omits the CLI flag, before the agent sees its first prompt.
   */
  private resolveAutoPublishFromState(
    state: TaskRunState | undefined,
  ): string | null {
    if (this.autoPublishStateResolved) {
      return null;
    }
    if (
      this.config.autoPublish === true ||
      this.config.createPr === false ||
      this.isAutomatedOrigin()
    ) {
      // The boot decision already publishes (or never may) — nothing to upgrade.
      this.autoPublishStateResolved = true;
      return null;
    }
    this.autoPublishStateResolved = true;
    if (state?.auto_publish !== true) {
      return null;
    }
    this.config.autoPublish = true;
    this.logger.debug("Run upgraded to auto-publish from run state");
    return [
      "IMPORTANT — OVERRIDE PREVIOUS INSTRUCTIONS ABOUT CREATING BRANCHES/PRs.",
      "The user has auto-publish enabled for this run. The review-first cloud task instructions in your system prompt are replaced by the following:",
      "",
      this.buildCloudSystemPrompt(this.detectedPrUrl),
    ].join("\n");
  }

  private buildExistingPrCheckoutInstruction(prUrl: string): string {
    return `Continue working on the existing PR branch. If it is not already checked out, check it out with \`gh pr checkout ${prUrl}\`. Do not check it out again when it is already active.`;
  }

  /**
   * Fire-and-overlap: starts the best-effort PR-branch checkout so it runs
   * concurrently with the rest of session setup, returning the promise (or
   * null when there is nothing to check out). Only runs when auto-publishing,
   * matching the system-prompt fallback's gate: a review-first run must not
   * silently check out a branch the prompt told the agent to leave alone.
   */
  private buildExistingPrCheckoutPromise(
    prUrl: string | null,
  ): Promise<ExistingPrCheckoutResult> | null {
    if (!prUrl || !this.config.repositoryPath) {
      return null;
    }
    if (!this.shouldAutoPublishCloudChanges()) {
      return null;
    }
    return checkoutExistingPullRequest({
      repositoryPath: this.config.repositoryPath,
      prUrl,
    });
  }

  /**
   * Consume a pre-checkout result without throwing — a transient `gh` failure
   * must fall back to the agent's own checkout (via the system-prompt
   * instruction), never abort session start.
   */
  private logExistingPrCheckoutResult(
    prUrl: string | null,
    result: ExistingPrCheckoutResult,
  ): void {
    if (result.status === "failed") {
      this.logger.warn(
        "Existing PR pre-checkout failed; agent will retry if needed",
        {
          prUrl,
          error: result.error,
        },
      );
    } else {
      this.logger.debug("Existing PR branch prepared before session start", {
        prUrl,
        branch: result.branch,
        alreadyActive: result.status === "already_active",
      });
    }
  }

  private buildDetectedPrContext(prUrl: string): string {
    if (!this.shouldAutoPublishCloudChanges()) {
      return (
        `An open pull request already exists: ${prUrl}\n` +
        `Use that PR as context if it is helpful, but stop with local changes ready for review.\n` +
        `Do NOT create commits, push to the PR branch, update the pull request, create a new branch, or create a new pull request unless the user explicitly asks.`
      );
    }

    return (
      `IMPORTANT — OVERRIDE PREVIOUS INSTRUCTIONS ABOUT CREATING BRANCHES/PRs.\n` +
      `You already have an open pull request: ${prUrl}\n` +
      `Unless the user explicitly asks for a new branch or separate PR, you MUST:\n` +
      `1. ${this.buildExistingPrCheckoutInstruction(prUrl)}\n` +
      `2. Make changes, commit, and push to that branch\n` +
      `By default, do not create a new branch, close the existing PR, or create a new PR — continue on the existing PR. If the user explicitly asks you to create a new branch or a separate PR, follow their instruction instead.`
    );
  }

  /**
   * How this run may hand a deliverable to the Slack thread it is answering in.
   *
   * The offer has to match what delivery will actually accept: naming an adapter the
   * workspace cannot use gets the request rejected server-side after the agent has already
   * promised the user a canvas or a spreadsheet. The backend resolves that capability from
   * the workspace's feature flags and Slack scopes when the task starts and hands it to us
   * on the run state, so the wording lives here and the gating stays there.
   */
  private buildSlackDeliveryInstructions(): string {
    if (this.slackArtifactDelivery === null) {
      return "";
    }

    if (this.slackArtifactDelivery === "none") {
      return `
## Delivering to Slack
- You do not have artifact delivery in this workspace: you cannot create or share artifacts (files, canvases, documents) from this run, so do not attempt to. Deliver results as plain text in your reply.
- Do not attach, upload, link to, or expose run artifacts or local working files, including /tmp/workspace paths.`;
    }

    const endpoint = `$POSTHOG_API_URL/api/projects/$POSTHOG_PROJECT_ID/tasks/$POSTHOG_TASK_ID/runs/$POSTHOG_TASK_RUN_ID/living_artifacts/`;
    const preamble = `
## Delivering to Slack
- Local sandbox paths such as /tmp/workspace/... are not visible to Slack users.
- Do not say a file, report, PDF, spreadsheet, document, or other artifact is attached, uploaded, or shared unless a tool explicitly confirms that delivery.
- Run artifacts that are not your uploaded outputs (plans, context, tree snapshots, user uploads) are internal: never deliver them to Slack or mention them in your reply.`;

    // Charts attach to both modes: they post as an image block referencing a PostHog-hosted
    // url, so they work wherever the workspace can post at all.
    const chartBullets = this.slackChartDelivery
      ? `
- When an analytics answer is naturally visual (a trend over time, funnel, breakdown comparison, retention curve), deliver a chart image by default alongside the summary. Do not wait for the user to say "chart". Skip the image only when the result is a single number, a short list, or the user asked for raw data.
- To show a chart in Slack (a saved insight or an ad-hoc analytics query result), make a single call: POST to \`${endpoint}chart/\` with \`$POSTHOG_PERSONAL_API_KEY\` and body \`{"name": "<chart title>", "query": <query JSON, e.g. {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", ...}}>}\`, or \`{"name": "<chart title>", "insight_id": <numeric insight id>}\` for a saved insight. It renders the chart server-side and registers it for Slack delivery in one step, blocking until done (typically a few seconds).
- The chart renders directly under your answer text with its name as the title, so do not restate the title or announce the chart ("Here's a chart of…"). Spend your answer text on the takeaway instead: the trend, inflection points, spikes, or drops a reader should notice, with numbers where they matter. Each chart is delivered with an "Open in PostHog" button, so do not paste the response \`url\` into your answer unless the user explicitly asks for a link. Do not download, view, or re-upload the image yourself.
- Report a chart failure rather than retrying blindly: a 400 carries the reason in \`error\`, or in \`detail\` when the request body itself was rejected, and a 429 means the project's chart render limit is saturated, so answer without the chart.
- SQL results cannot be charted yet, because the chart endpoint rejects SQL queries. Chart with an insight query (e.g. TrendsQuery) when the question can be expressed as one; otherwise summarize the SQL result in your answer text.`
      : "";

    if (this.slackArtifactDelivery === "message") {
      const chartException = this.slackChartDelivery
        ? " Chart images are the one exception: deliver them through the dedicated chart endpoint below, never through the generic living-artifacts endpoint."
        : "";
      const unsupportedDeliverable = this.slackChartDelivery
        ? "- If a deliverable cannot be expressed as a Slack message or a chart image (for example .xlsx/.pdf/.docx), say that plainly and summarize the result in Slack instead."
        : "- If a deliverable cannot be expressed as a Slack message (for example .xlsx/.pdf/.docx), say that plainly and summarize the result in Slack instead.";
      return `${preamble}
- You do not have canvas or file delivery in this workspace: do not use the \`slack_canvas\` or \`slack_file\` adapters, and do not promise a canvas, uploaded spreadsheet, or downloadable file.${chartException}
- For Slack deliverables, create a living artifact before claiming delivery. POST to \`${endpoint}\` with \`$POSTHOG_PERSONAL_API_KEY\` using adapter \`slack_message\`. To update a prior deliverable, GET the returned artifact id or POST new \`content\` to \`${endpoint}<artifact_id>/edit/\`.${chartBullets}
${unsupportedDeliverable}`;
    }

    return `${preamble}
- For Slack deliverables, create a living artifact before claiming delivery. POST to \`${endpoint}\` with \`$POSTHOG_PERSONAL_API_KEY\`; choose adapter \`slack_canvas\`, \`slack_message\`, \`slack_file\`, or \`document_connector\`. Use \`adapter=slack_file\` with \`content_base64\` for binary deliverables such as .xlsx/.pdf/.docx, or \`source_artifact_id\` / \`source_storage_path\` for a file you already uploaded as a \`type=output\` run artifact.
- To update a prior deliverable, GET the returned artifact id or POST new \`content\`, \`content_base64\`, or source artifact fields to \`${endpoint}<artifact_id>/edit/\`.${chartBullets}
- Do not paste living-artifact Slack file links or permalinks into your final Slack answer unless the user explicitly asks for the URL. The Slack relay attaches pending file artifacts to your final answer automatically, so mention the artifact by name only if useful.
- If you created a local file but no upload or delivery tool is available, say that plainly and summarize the result in Slack instead.`;
  }

  /**
   * What to do when a cloud run has no way to reach the user's code.
   *
   * Repository access on a cloud run comes from the user's own GitHub connection in
   * PostHog, so a run can legitimately start without one — nothing is checked out and
   * there are no credentials to push with. The Slack mention path used to refuse those
   * mentions outright, which walled off every question that only looked like it needed
   * code; it now starts the run and leaves the judgement here, where the request itself
   * is visible. The settings link is built from this run's own host and project so it
   * lands the user in the right region rather than a hardcoded one.
   *
   * Appended to every cloud branch on purpose: a checkout is not proof of access. A
   * public repository clones with no token at all, so a run can hold the code and still
   * have no way to push it.
   */
  private buildSourceControlAccessInstructions(): string {
    const settingsUrl = `${this.config.apiUrl.replace(/\/$/, "")}/project/${this.config.projectId}/settings/user-personal-integrations`;
    return `
## When you cannot reach the code
You may have no repository checked out, or no credentials to push and open a pull request with.
- Answer the part of the request that does not need the code first — questions about PostHog, their data, or their configuration are all still answerable.
- If the request turns out not to need a code change at all, just answer it and say nothing about GitHub.
- Only if it genuinely needs a code change, say so plainly and link them to ${settingsUrl} to connect GitHub, then ask them to come back to you.
- Do not work around it: no guessing at file contents you cannot read, and no starting a change you have no way to deliver.`;
  }

  private buildCloudSystemPrompt(
    prUrl?: string | null,
    slackThreadUrl?: string | null,
    inboxReportUrl?: string | null,
  ): string {
    const taskId = this.config.taskId;
    const shouldAutoCreatePr = this.shouldAutoPublishCloudChanges();
    const isSlack = this.getCloudInteractionOrigin() === "slack";
    const identityInstructions = isSlack
      ? `
# Identity
You are the PostHog Slack app, PostHog's agent for helping users with their product data and coding tasks from Slack. When introducing yourself or referring to yourself in messages to the user, identify as "PostHog Slack app". Do NOT refer to yourself as Claude, an Anthropic assistant, or any underlying model name.

# Response Style
You are replying in a Slack thread. Slack readers want short, skimmable answers — be concise by default.
- Answer simple questions in a single sentence. Keep everything else brief — a few sentences at most.
- Lead with the answer or the outcome. Skip preamble, restating the question, and sign-offs.
- Prefer plain prose. Treat bullet lists as the exception, not the norm, and avoid headers and tables unless they genuinely make a complex answer clearer.
- Do not narrate your thinking or list every step you took; report what matters and the result.
- This is a default, not a hard rule. If the user (or their saved memory) asks for more depth or a specific format, follow that instead.

# PostHog products first
PostHog is a product suite, not just analytics — session replay, feature flags, experiments, surveys, error tracking, logs, data warehouse, CDP, messaging, and customer support all ship as PostHog products.
- When someone asks how to set up, enable, configure, or use a capability, assume they mean PostHog's version of it and answer about that.
- Search our docs with the \`docs-search\` tool before you answer, and ground the answer in what it returns rather than in what you remember. The product changes faster than your training data.
- Never send the user to a third-party product for something PostHog does. If you are unsure whether we cover it, search the docs before concluding we don't — and if we genuinely don't, say so plainly instead of recommending a competitor. Pointing at a third party we integrate with, as a source or destination, is fine.
- When a request could mean either a PostHog feature or something in the user's own codebase, ask which they mean instead of guessing.

# Mentioning users
To ping a Slack user, reuse a \`<@U…|displayname>\` token that already appears in the message context — copy it verbatim, including the \`U…\` ID. Do NOT construct a mention token from a name, and do NOT substitute the display name (or any other string) for the \`U…\` ID — \`<@Jane|Jane Doe>\` is not a valid mention; only the form with the real ID like \`<@U01ABCDEF23|Jane Doe>\` is. If the person you want to refer to has no \`<@U…|displayname>\` token anywhere in the thread context, write their name as plain text instead of inventing one. These \`<@U…>\` tokens are Slack-only: never carry one — or a name or handle derived from it — into a GitHub PR, commit message, or review request as an \`@\`-mention. A Slack display name or handle is NOT a GitHub username; see the pull-request instructions below.

# Suggesting code changes
You can also open pull requests directly from this Slack thread. When the user's question describes a problem with a plausible code-side fix — a bug visible in errors or logs, missing or broken instrumentation, a broken funnel step traceable to UI code, a stale config that lives in a repo — end your reply with a one-sentence offer to open a PR for the fix and ask if they want you to proceed. Skip the offer for pure data lookups with no actionable code change (e.g. "what was DAU yesterday?"), and skip it when the fix would clearly live outside any repo you can reach.
`
      : "";
    const signedCommitInstructions = `
## Committing (signed commits required)
Commits MUST be signed. \`git commit\` and \`git push\` are blocked in this environment.
To commit: stage your changes with \`git add\`, then call the \`git_signed_commit\` tool (full
name \`${SIGNED_COMMIT_QUALIFIED_TOOL_NAME}\`) with a \`message\` (and optional \`body\`/\`paths\`).
It creates a GitHub-signed ("Verified") commit on the branch and keeps your local checkout in
sync. To start a new branch, pass \`branch\` (prefixed with \`posthog/\`) — the tool creates
it on the remote for you.

## Updating from the base branch
To bring the base branch into your PR branch, call the \`git_signed_merge\` tool (full name
\`${SIGNED_MERGE_QUALIFIED_TOOL_NAME}\`) — it creates a Verified two-parent merge commit
server-side (like GitHub's "Update branch" button). NEVER run \`git merge\` followed by
\`git_signed_commit\`: a merge in progress is refused, because the commit API would linearize
the merge and dump every base-branch change into your PR. If \`git_signed_merge\` reports a
conflict, fix it with a rebase instead: \`git rebase origin/<base>\`, resolve, \`git rebase
--continue\`, then call \`git_signed_rewrite\`.

## Rewriting / force-pushing (rebases, conflict fixes)
\`git push --force\` is also blocked. To update a branch after a local rebase or conflict
resolution, rebase locally with normal \`git\` (resolve conflicts and finish with
\`git rebase --continue\`, NOT \`git commit\`), then call the \`git_signed_rewrite\` tool (full
name \`${SIGNED_REWRITE_QUALIFIED_TOOL_NAME}\`). It republishes the branch's commits as Verified
and atomically force-updates the remote branch. This is how you fix conflicts on an existing PR.
Histories containing merge commits are refused — rebase (which flattens merges) first.
If a signed-git tool refuses with a "merge in progress" or "leak" error, follow its recovery
instructions instead of retrying the same call.

## Re-committing to a branch with an open PR
Before committing again to a branch that already has an open PR, fetch it first. The remote
branch can advance between your commits — CI automation often auto-commits regenerated
artifacts (codegen, lockfiles, formatting) onto open PR branches, and collaborators can push
too. Committing from a stale local checkout silently reverts those commits, so
\`git_signed_commit\` refuses when the remote branch is ahead of your checkout. If it does, or
before your next commit, update your checkout — stash any uncommitted work across the update so
you don't lose it: \`git stash --include-untracked\`, \`git fetch origin <branch>\`,
\`git reset --hard origin/<branch>\`, \`git stash pop\` (resolve any conflicts), then re-stage
and commit. A soft/mixed reset would keep your stale files and re-commit the revert, so the
hard reset is the safe one here — your work is held in the stash.

## Attribution
Do NOT add "Co-Authored-By" trailers or "Generated with [Claude Code]" lines to your
commit messages. The \`git_signed_commit\` tool automatically appends the only trailers
we want:
  Generated-By: PostHog Desktop
  Task-Id: ${taskId}`;

    // A stack is several PRs, so this would contradict the review-first modes.
    const stackInstructions = shouldAutoCreatePr
      ? `
## Stacked pull requests
Stack only when the layers are independently reviewable (schema, then backend, then UI) or the
user asked for a stack. Keep stacks shallow — 2 to 4 layers. One PR remains the default.
Do NOT use the \`gh stack\` CLI: its publishing commands (\`submit\`, \`sync\`, \`push\`, \`link\`)
all run \`git push\`, which is blocked here. Build the stack this way instead:
1. Commit the bottom layer with \`git_signed_commit\`, passing \`branch\`, then open its pull
   request based on the base branch.
2. For each layer above, commit with \`git_signed_commit\` and a new \`branch\` — your checkout
   already sits on the layer below, so the branch starts there — then open its pull request
   based on the branch of the layer below (\`--base <that branch>\`).
3. Link them with the \`gh_stack\` tool (full name \`${GH_STACK_QUALIFIED_TOOL_NAME}\`),
   operation "create", passing \`pull_requests\` bottom to top. Every layer must target the
   branch of the one below it, or the link is refused.
When a lower layer changes, restack the layers above it bottom-first. For each layer: check
that layer out, \`git rebase <its parent branch>\`, then republish it with
\`git_signed_rewrite\` passing \`onto\` = the parent branch. Check the layer out every time —
\`git_signed_rewrite\` replays whatever your local HEAD points at and uses \`branch\` only to
pick which remote ref moves, so rewriting from the wrong checkout publishes the wrong history
to that layer.`
      : "";

    const prLinkInstructions = `
## Referencing pull requests
When you mention a pull request in any reply or summary, always hyperlink it to its full URL
(e.g. a Markdown link like [#123](https://github.com/org/repo/pull/123)) rather than plain
text, so readers can open it directly.`;

    const shellEfficiencyInstructions = `
## Shell efficiency
Optimize for the fewest shell round trips.
- Batch related commands into one Bash invocation using \`&&\` (e.g. \`npm run typecheck && npm run lint && npm test\`).
- Emit all independent tool calls in the same response.
- Read multiple files at once.
- Never rerun a command solely to reproduce output you already have.`;

    const artifactInstructions = `
## Delivering non-code files (artifacts)
When you create a non-code file the user should be able to download (such as a report, chart, image, archive, or data file), call the \`upload_artifact\` tool with its path before your final reply. In your final reply, link to the download URL returned by the tool—never link to the file's local workspace path. Files left in the workspace don't reach the user. Don't upload source code or repository changes—those belong in a commit or PR.`;

    // Closes out every branch below, so a new section is added once rather than five times.
    const commonInstructions = `${signedCommitInstructions}${stackInstructions}${prLinkInstructions}${shellEfficiencyInstructions}${artifactInstructions}${this.buildSlackDeliveryInstructions()}${this.buildSourceControlAccessInstructions()}`;

    const whyContextInstruction = `   - Add a brief **Why** to the body — one or two sentences capturing the reason the user asked for this change (the motivation, not a restatement of the diff). Keep it short.`;
    const publicRepoSafetyInstruction = `   - **Public-repo safety.** Treat the target repository as public-readable unless you have verified otherwise. The PR title, description, and commit messages must not contain private operational scale (exact event counts, internal row volumes, customer-usage percentages), customer names / emails / companies, references to internal tickets or incidents, the contents of Slack threads (do not quote or paraphrase what was said), or unreleased roadmap details. Linking to the originating Slack thread is fine and encouraged — Slack links are auth-gated and useful as context — as are channel references like "raised in #team-foo". Describe findings qualitatively ("present on nearly all X events, absent from Y") rather than with quantitative figures pulled from analytics queries — the reasoning that uses those numbers can stay in the thread; the PR copy cannot.`;
    const prMentionSafetyInstruction = `   - **Never guess a GitHub identity.** Do NOT \`@\`-mention, tag, assign, request review from, or attribute the PR to a person (in the title, description, commit message, or reviewers) using a name or handle taken from Slack or this thread. A Slack display name or handle is NOT a GitHub username. Finding a similar-looking handle in the repo's git history, CODEOWNERS, or existing PRs/issues does NOT confirm it belongs to this person: repository presence proves the handle exists, not that it is the person you mean, so treating it as a match still \`@\`-tags an unrelated account (e.g. Slack "Ross" is not necessarily GitHub \`@ross\`, even if some \`@ross\` has committed to the repo). Only \`@\`-mention a GitHub \`@handle\` the user gave you explicitly in this thread. Otherwise refer to people by plain-text name, or omit the mention entirely.`;
    // Slack- and inbox-originated PRs are attributed to PostHog, not the
    // PostHog Desktop app — they come from the Slack app / Self-driving
    // inbox, which users know as "PostHog".
    const createdWith = this.isAutomatedOrigin()
      ? "Created with [PostHog](https://posthog.com?ref=pr)"
      : "Created with [PostHog Desktop](https://posthog.com/desktop?ref=pr)";
    const prFooter = slackThreadUrl
      ? `*${createdWith} from a [Slack thread](${slackThreadUrl})*`
      : inboxReportUrl
        ? `*${createdWith} from an [inbox report](${inboxReportUrl})*`
        : `*${createdWith}*`;
    const repositoryWorkspaceInstructions =
      this.taskRepositories.length > 1
        ? `The task workspace contains these repositories:
${this.taskRepositories.map((repository) => `- ${repository}: /tmp/workspace/repos/${repository.toLowerCase()}`).join("\n")}

Apply the repository workflow below separately in every repository you change. Keep branches, commits, diffs, and pull requests repository-specific.`
        : "";

    if (prUrl) {
      if (!shouldAutoCreatePr) {
        return `${identityInstructions}
# Cloud Task Execution

This task already has an open pull request: ${prUrl}

Do the requested work, but stop with local changes ready for review.

Important:
- Do NOT create new commits, push to the branch, or update the pull request unless the user explicitly asks.
- Do NOT create a new branch or a new pull request unless the user explicitly asks.
${commonInstructions}
`;
      }

      return `${identityInstructions}
# Cloud Task Execution

This task already has an open pull request: ${prUrl}

After completing the requested changes:
1. ${this.buildExistingPrCheckoutInstruction(prUrl)}
2. Stage your changes with \`git add\`, then call the \`git_signed_commit\` tool with a clear \`message\` (do NOT use \`git commit\`/\`git push\` — they are blocked). This commits to the existing PR branch.
   - If the branch is behind its base, call the \`git_signed_merge\` tool first — it merges the base in server-side with a Verified merge commit. Only if it reports a conflict: fetch and rebase locally (\`git fetch origin <base>\`, \`git rebase origin/<base>\`, resolve, \`git rebase --continue\`), then call the \`git_signed_rewrite\` tool to force-update this same PR branch.
3. For every PR review comment or review thread you addressed, treat the thread as done only after BOTH of these:
   - Reply on the thread with a short note describing what changed (reference the commit SHA when useful) using \`gh api -X POST /repos/{owner}/{repo}/pulls/{n}/comments/{id}/replies -f body='...'\`.
   - Resolve the thread via the \`resolveReviewThread\` GraphQL mutation: \`gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id="<thread-node-id>"\`.
   List unresolved threads first with \`gh api graphql -f query='{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<n>){reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{body}}}}}}}'\` so you can resolve each one you fixed.

Important:
- Do NOT create a new branch or a new pull request unless the user explicitly asks.
- Do NOT push fixes for review comments without replying to and resolving each related thread.
${commonInstructions}
`;
    }

    if (!this.config.repositoryPath && this.taskRepositories.length === 0) {
      const repositoryInstructions = `
When the task requires a GitHub repository:
- If the repository is not specified, call \`list_repos\` and use the task context to choose it. If multiple repositories remain plausible, ask the user.
- Call \`clone_repo\` with the chosen \`owner/repo\` and optional branch. It creates a shallow clone under \`/tmp/workspace/repos/<owner>/<repo>\` and returns the path.
- Work from inside the returned path for all code changes.
- The clone starts with one commit. If older history is genuinely needed, fetch it in bounded steps with \`git fetch --deepen=50 origin <branch>\`, then \`git fetch --deepen=200 origin <branch>\`. Use \`git fetch --unshallow\` only when the task explicitly requires full history, such as a long-range blame or bisect.
`;
      const publishInstructions =
        this.config.createPr === false
          ? `
When the user asks for code changes:
- You may make local edits in a repository cloned with \`clone_repo\`
- Do NOT create branches, commits, push changes, or open pull requests in this run`
          : shouldAutoCreatePr
            ? `
When the user asks for code changes in a GitHub repository:
- After completing code changes in a cloned repository, create a branch, stage your changes with \`git add\` and commit them with the \`git_signed_commit\` tool (do NOT use \`git commit\`/\`git push\` — they are blocked), and open a draft pull request from inside the clone without waiting to be asked. Before opening the PR, check the cloned repo for a PR template at \`.github/pull_request_template.md\` (or variants; fall back to the org's \`.github\` repo via \`gh api\`) and use it as the body structure, and search for matching open issues with \`gh issue list --search\` to include \`Closes #<n>\` / \`Refs #<n>\` links.
- Keep the PR description brief overall. Summarize only the most important changes — do NOT enumerate every change you made. A few sentences or bullets is plenty.
${whyContextInstruction.trimStart()}
${publicRepoSafetyInstruction.trimStart()}
${prMentionSafetyInstruction.trimStart()}
- End the PR description with a horizontal rule followed by this footer line: ${prFooter}
- Always create the PR as a draft. Do not ask for confirmation before publishing completed code changes`
            : `
When the user explicitly asks for code changes in a GitHub repository:
- If the user explicitly asks you to open or update a pull request, create a branch, stage your changes with \`git add\` and commit them with the \`git_signed_commit\` tool (do NOT use \`git commit\`/\`git push\` — they are blocked), and open a draft pull request from inside the clone. Before opening the PR, check the cloned repo for a PR template at \`.github/pull_request_template.md\` (or variants; fall back to the org's \`.github\` repo via \`gh api\`) and use it as the body structure, and search for matching open issues with \`gh issue list --search\` to include \`Closes #<n>\` / \`Refs #<n>\` links.
- Keep the PR description brief overall. Summarize only the most important changes — do NOT enumerate every change you made. A few sentences or bullets is plenty.
${whyContextInstruction.trimStart()}
${publicRepoSafetyInstruction.trimStart()}
${prMentionSafetyInstruction.trimStart()}
- End the PR description with a horizontal rule followed by this footer line: ${prFooter}
- Do NOT create branches, commits, push changes, or open pull requests unless the user explicitly asks for that`;

      return `${identityInstructions}
# Cloud Task Execution — No Repository Mode

You are a helpful assistant with access to PostHog via MCP tools. You can help with both code tasks and data/analytics questions.

When the user asks about analytics, data, metrics, events, funnels, dashboards, feature flags, experiments, or anything PostHog-related:
- Use the canonical \`posthog:exec\` tool to query data, search insights, and provide real answers
- Follow its built-in instructions to discover and invoke inner tools
- Do NOT tell the user to check an external analytics platform — you ARE the analytics platform
- Inner tools include \`posthog:read-data-schema\`, \`posthog:execute-sql\`, \`posthog:insight-query\`, and the typed query tools

When the user asks for code changes or software engineering tasks:
- Choose and clone a repository only when the task requires one. For questions and analysis, answer without cloning when possible.
${repositoryInstructions}${publishInstructions}

Important:
- Prefer using MCP tools to answer questions with real data over giving generic advice.
${commonInstructions}
`;
    }

    if (!shouldAutoCreatePr) {
      return `${identityInstructions}
# Cloud Task Execution

${repositoryWorkspaceInstructions}

Do the requested work, but stop with local changes ready for review.

Important:
- Do NOT create a branch, commit, push, or open a pull request unless the user explicitly asks.
- If the user explicitly asks you to open a pull request: pick a new branch name prefixed with \`posthog/\`, stage your changes with \`git add\`, and call the \`git_signed_commit\` tool with \`branch\` set to that name and a clear \`message\` (do NOT use \`git commit\`/\`git push\` — they are blocked). Before opening the PR, check the repo for a PR template at \`.github/pull_request_template.md\` (or variants; fall back to the org's \`.github\` repo via \`gh api\`) and use it as the body structure, and search for matching open issues with \`gh issue list --search\` to include \`Closes #<n>\` / \`Refs #<n>\` links. Keep the description brief overall — summarize only the most important changes.
${whyContextInstruction.trimStart()}
${publicRepoSafetyInstruction.trimStart()}
${prMentionSafetyInstruction.trimStart()}
- End the PR description with a horizontal rule followed by this footer line: ${prFooter}
- Always create the PR as a draft.
${commonInstructions}
`;
    }

    return `${identityInstructions}
# Cloud Task Execution

${repositoryWorkspaceInstructions}

If the work you are being asked to do already has an open pull request — for example, the inbox report you fetched links an implementation PR (its \`implementation_pr_url\`), or this same thread already produced a PR that you are now being asked to revise — do NOT open a second PR. Check that PR out with \`gh pr checkout <url>\`, continue on its branch, and commit your changes to it with the \`git_signed_commit\` tool (if the branch is behind its base, call \`git_signed_merge\` first). A PR is only the one to continue if it is for this same request; if the thread merely mentions an unrelated or older PR, ignore it. Only open a new, separate PR when the change is genuinely distinct from the existing one.

Otherwise, after completing the requested changes:
1. Pick a new branch name prefixed with \`posthog/\` (e.g. \`posthog/fix-login-redirect\`)
2. Stage your changes with \`git add\`, then call the \`git_signed_commit\` tool with \`branch\` set to that name and a clear \`message\` (do NOT use \`git commit\`/\`git push\` — they are blocked). The tool creates the branch on the remote and a signed commit on it.
3. Before opening the PR, prepare the body:
   - Keep the PR description brief overall. Summarize only the most important changes — do NOT enumerate every change you made. A few sentences or bullets is plenty.
${whyContextInstruction}
${publicRepoSafetyInstruction}
${prMentionSafetyInstruction}
   - Check the repo for a PR template at \`.github/pull_request_template.md\` (also try \`.github/PULL_REQUEST_TEMPLATE.md\`, \`docs/pull_request_template.md\`, and root variants). If one exists, use its exact section headings as the PR body — do NOT fall back to a generic Summary/Test plan format.
   - If no repo-level template exists, check the org's \`.github\` repo via \`gh api /repos/<owner>/.github/contents/.github/pull_request_template.md\` (and other common paths) and use that as a fallback.
   - Search for matching open issues with \`gh issue list --state open --search '<keywords>'\` (derive keywords from the branch name, commits, and changed files; \`gh issue view <n>\` to confirm relevance). For every issue this PR would resolve, include a \`Closes #<n>\` line in the body so GitHub auto-links and auto-closes it on merge. For issues that are related but not fully resolved, use \`Refs #<n>\` instead.
4. Create a draft pull request using \`gh pr create --draft${this.config.baseBranch ? ` --base ${this.config.baseBranch}` : ""}\` with a descriptive title and the body prepared above. Add the following footer at the end of the PR description:
\`\`\`
---
${prFooter}
\`\`\`

Important:
- Always create the PR as a draft. Do not ask for confirmation.
${commonInstructions}
`;
  }

  private async getCurrentGitBranch(): Promise<string | null> {
    if (!this.config.repositoryPath) {
      return null;
    }

    try {
      return await getCurrentBranch(this.config.repositoryPath);
    } catch (error) {
      this.logger.debug("Failed to determine current git branch", {
        repositoryPath: this.config.repositoryPath,
        error,
      });
      return null;
    }
  }

  // The checked-out branch and the GitHub repository its `origin` points at, or
  // null without a checkout (no-repository mode) or on a detached HEAD.
  private async getCurrentCheckout(): Promise<OwnedBranch | null> {
    const branch = await this.getCurrentGitBranch();
    if (!branch || !this.config.repositoryPath) return null;
    let repository: string | null = null;
    try {
      repository = parseGithubRemoteRepository(
        await getRemoteUrl(this.config.repositoryPath),
      );
    } catch (error) {
      this.logger.debug("Failed to determine git origin", {
        repositoryPath: this.config.repositoryPath,
        error,
      });
    }
    return { repository, branch };
  }

  private async syncCloudBranchMetadata(payload: JwtPayload): Promise<void> {
    const branchName = await this.getCurrentGitBranch();
    if (!branchName || branchName === this.lastReportedBranch) {
      return;
    }

    try {
      await this.posthogAPI.updateTaskRun(payload.task_id, payload.run_id, {
        branch: branchName,
        output: { head_branch: branchName },
      });
      this.lastReportedBranch = branchName;
    } catch (error) {
      this.logger.debug("Failed to attach current branch to task run", {
        taskId: payload.task_id,
        runId: payload.run_id,
        branchName,
        error,
      });
    }
  }

  /**
   * Ends the run's telemetry (root span + final flush) at the in-sandbox
   * terminal point of a background run. Sandbox teardown cannot be relied on
   * for this: agent-server is an exec'd process inside the sandbox, so
   * `docker stop` signals only the container's PID 1 and Modal terminate is
   * immediate — the SIGTERM handler (and thus cleanupSession) never runs, and
   * an unended root span would never export. Once the background prompt
   * settles the run is over in-sandbox; the workflow marks the terminal
   * status and destroys the sandbox right after.
   */
  private async finalizeRunTelemetry(payload: JwtPayload): Promise<void> {
    if (this.getEffectiveMode(payload) !== "background") return;
    try {
      await this.session?.telemetry?.shutdown();
    } catch (error) {
      this.logger.debug("Failed to finalize run telemetry", error);
    }
  }

  private async signalTaskComplete(
    payload: JwtPayload,
    stopReason: string,
    errorMessage?: string,
  ): Promise<void> {
    if (this.session?.payload.run_id === payload.run_id) {
      try {
        await this.session.logWriter.flush(payload.run_id, {
          coalesce: true,
        });
      } catch (error) {
        this.logger.debug("Failed to flush session logs before completion", {
          taskId: payload.task_id,
          runId: payload.run_id,
          error,
        });
      }
    }

    if (stopReason !== "error") {
      this.logger.debug("Skipping status update for non-error stop reason", {
        stopReason,
      });
      return;
    }

    const status = "failed";

    this.enqueueTaskTerminalEvent(POSTHOG_NOTIFICATIONS.ERROR, {
      source: "agent_server",
      stopReason,
      error: errorMessage ?? "Agent error",
    });

    try {
      await this.posthogAPI.updateTaskRun(payload.task_id, payload.run_id, {
        status,
        error_message: errorMessage ?? "Agent error",
      });
      this.logger.debug("Task completion signaled", { status, stopReason });
    } catch (error) {
      this.logger.error("Failed to signal task completion", error);
    } finally {
      await this.emitRtkSavings();
      await this.eventStreamSender?.stop();
      // The run is terminal and the sandbox is torn down right after — and
      // teardown kills this exec'd process without SIGTERM, so this is the
      // last chance to end the root span and drain the OTel queues. The
      // error mirror was appended above, so the root span exports as ERROR.
      await this.session?.telemetry?.shutdown().catch(() => {});
    }
  }

  private enqueueTaskTerminalEvent(
    method:
      | typeof POSTHOG_NOTIFICATIONS.TASK_COMPLETE
      | typeof POSTHOG_NOTIFICATIONS.ERROR,
    params: Record<string, unknown>,
  ): void {
    const entry = {
      type: "notification" as const,
      timestamp: new Date().toISOString(),
      notification: {
        jsonrpc: "2.0" as const,
        method,
        params,
      },
    };
    this.eventStreamSender?.enqueue(entry);
    // Terminal events bypass the SessionLogWriter (and its sinks), so mirror
    // them onto the OTel writer directly — a failed run is exactly what the
    // telemetry must record.
    this.session?.telemetry?.append(this.session.payload.run_id, entry);
  }

  private configureEnvironment({
    isInternal = false,
    originProduct,
    signalReportId,
    aiStage,
    taskId,
    taskRunId,
    taskUserId,
    taskTitle,
    taskOriginKey,
    repositories,
    runtimeAdapter,
    sandboxEnvironmentId,
    snapshotKind,
    prewarmed,
    executionEnvironment,
  }: {
    isInternal?: boolean;
    originProduct?: Task["origin_product"] | null;
    signalReportId?: string | null;
    aiStage?: string | null;
    taskId?: string | null;
    taskRunId?: string | null;
    taskUserId?: number | null;
    taskTitle?: string | null;
    taskOriginKey?: string | null;
    repositories?: string[];
    runtimeAdapter?: string | null;
    sandboxEnvironmentId?: string | null;
    snapshotKind?: string | null;
    prewarmed?: boolean | null;
    executionEnvironment?: "local" | "cloud";
  } = {}): GatewayEnv {
    const { apiKey, apiUrl, projectId } = this.config;
    const product = resolveGatewayProduct({ isInternal, originProduct });
    // Go-gateway runs authenticate with the per-run scoped token minted by the
    // worker (pinned product + on-behalf-of team, per-run spend cap), not the
    // run's per-team OAuth token, whose team has no gateway wallet. A routed
    // product with no token therefore stays on the Python gateway.
    const gatewayToken = process.env.AI_GATEWAY_TOKEN?.trim() || undefined;
    let target = resolveGatewayTarget({
      product,
      aiStage,
      posthogHost: apiUrl,
    });
    if (target.isAiGateway && !gatewayToken) {
      this.logger.warn(
        `AI_GATEWAY_TOKEN missing for routed product ${target.aiProduct}; falling back to the Python gateway`,
      );
      target = resolveGatewayTarget({
        product,
        aiStage,
        posthogHost: apiUrl,
        env: { ...process.env, AI_GATEWAY_URL: undefined },
      });
    }
    const { baseUrl: gatewayUrl, isAiGateway, aiProduct } = target;
    const llmBearer = isAiGateway && gatewayToken ? gatewayToken : apiKey;
    const openaiBaseUrl = gatewayUrl.endsWith("/v1")
      ? gatewayUrl
      : `${gatewayUrl}/v1`;
    // Forward task metadata as `x-posthog-property-*` headers so the gateway
    // lifts them onto the $ai_generation event. The Claude path routes these
    // through the Anthropic SDK's ANTHROPIC_CUSTOM_HEADERS env var; the codex
    // path sets them as `model_providers.posthog.http_headers` instead, so we
    // also expose the record form below.
    const gatewayProperties = {
      task_origin_product: originProduct,
      task_internal: isInternal,
      signal_report_id: signalReportId,
      ai_stage: aiStage,
      task_id: taskId,
      task_run_id: taskRunId,
      task_user_id: taskUserId,
      task_title: taskTitle,
      task_origin_key: taskOriginKey,
      task_repositories: repositories?.length
        ? JSON.stringify(repositories)
        : null,
      task_runtime_adapter: runtimeAdapter,
      task_sandbox_environment_id: sandboxEnvironmentId,
      task_snapshot_kind: snapshotKind,
      task_prewarmed: prewarmed,
      task_execution_environment: executionEnvironment ?? "cloud",
    };
    // The Claude path appends the project scope in buildEnvironment from
    // POSTHOG_PROJECT_ID; the codex path has no such hook, so its record below
    // carries the same scope.
    let customHeaders: string;
    let openaiCustomHeaders: Record<string, string>;
    if (isAiGateway) {
      // The Go gateway reads one X-PostHog-Properties JSON blob and ignores
      // per-property headers, and it has no product route, so `ai_product`
      // has to travel in the blob or the spend lands unattributed. `team_id`
      // is included for both adapters because the Go gateway does not read
      // the Python gateway's project-scope header.
      const properties = {
        ...gatewayProperties,
        ai_product: aiProduct,
        team_id: projectId,
      };
      customHeaders = buildPosthogPropertiesHeaderLines(properties);
      openaiCustomHeaders = buildPosthogPropertiesHeaderRecord(properties);
    } else {
      customHeaders = buildPosthogScopedPropertyHeaderLines(
        gatewayProperties,
        projectId,
      );
      // No $ai_session_id on the Go-gateway path above: it strips $-prefixed
      // blob keys, so the session id would be silently dropped there.
      openaiCustomHeaders = buildPosthogScopedPropertyHeaderRecord(
        {
          ...gatewayProperties,
          team_id: projectId,
          $ai_session_id: taskId,
        },
        projectId,
      );
    }

    // Server-level constants that don't vary per task — safe to keep in
    // process.env so spawned tools (PostHog MCP, workspace-server, etc.) can
    // reach the PostHog API without explicit threading.
    Object.assign(process.env, {
      POSTHOG_API_KEY: apiKey,
      POSTHOG_API_URL: apiUrl,
      POSTHOG_API_HOST: apiUrl,
      POSTHOG_AUTH_HEADER: `Bearer ${apiKey}`,
      POSTHOG_PROJECT_ID: String(projectId),
    });

    // Task-specific gateway config is returned rather than written to
    // process.env so that concurrent sessions do not clobber each other's
    // gateway URL, auth token, or custom headers.
    return {
      anthropicBaseUrl: gatewayUrl,
      anthropicAuthToken: llmBearer,
      openaiBaseUrl,
      openaiApiKey: llmBearer,
      anthropicCustomHeaders: customHeaders,
      openaiCustomHeaders,
      posthogProjectId: String(projectId),
    };
  }

  private buildSlackQuestionRelayResponse(
    payload: JwtPayload,
    toolMeta: Record<string, unknown> | null | undefined,
  ): RequestPermissionResponse {
    this.relaySlackQuestion(payload, toolMeta);
    return {
      outcome: { outcome: "cancelled" as const },
      _meta: {
        message:
          "This question has been relayed to the Slack thread where this task originated. " +
          "The user will reply there. Do NOT re-ask the question or pick an answer yourself. " +
          "Simply let the user know you are waiting for their reply.",
      },
    };
  }

  private shouldBlockPublishPermission(
    params: RequestPermissionRequest,
  ): boolean {
    if (this.config.createPr !== false) {
      return false;
    }

    const meta =
      params.toolCall?._meta &&
      typeof params.toolCall._meta === "object" &&
      !Array.isArray(params.toolCall._meta)
        ? (params.toolCall._meta as Record<string, unknown>)
        : null;
    const rawInput =
      params.toolCall?.rawInput &&
      typeof params.toolCall.rawInput === "object" &&
      !Array.isArray(params.toolCall.rawInput)
        ? (params.toolCall.rawInput as Record<string, unknown>)
        : null;
    const toolName = typeof meta?.toolName === "string" ? meta.toolName : null;
    const command =
      typeof rawInput?.command === "string" ? rawInput.command : null;

    return Boolean(
      toolName &&
        (toolName === "Bash" || toolName.includes("bash")) &&
        command &&
        /\bgit\s+push\b|\bgh\s+pr\s+(create|edit|ready|merge)\b/.test(command),
    );
  }

  private readPermissionMcpDescriptor(
    params: RequestPermissionRequest,
  ): { server: string; tool: string } | undefined {
    const descriptor = readMcpToolDescriptor(params.toolCall?._meta);
    if (descriptor) return descriptor;

    const rawInput = params.toolCall?.rawInput as
      | { toolName?: unknown }
      | undefined;
    return typeof rawInput?.toolName === "string"
      ? parseMcpToolName(rawInput.toolName)
      : undefined;
  }

  private matchesPostHogExecPermissionRequest(
    params: RequestPermissionRequest,
  ): string | null {
    const descriptor = this.readPermissionMcpDescriptor(params);
    if (!descriptor || !isPostHogExecDescriptor(descriptor)) return null;

    const subTool = extractPostHogSubTool(params.toolCall?.rawInput);
    return subTool &&
      matchesPostHogExecPermission(subTool, this.posthogExecPermissionRegex)
      ? subTool
      : null;
  }

  private createCloudClient(payload: JwtPayload) {
    const mode = this.getEffectiveMode(payload);
    const interactionOrigin =
      process.env.POSTHOG_CODE_INTERACTION_ORIGIN ??
      process.env.CODE_INTERACTION_ORIGIN ??
      process.env.TWIG_INTERACTION_ORIGIN;

    return {
      requestPermission: async (
        params: RequestPermissionRequest,
      ): Promise<RequestPermissionResponse> => {
        this.logger.debug("Permission request", {
          mode,
          interactionOrigin,
          kind: params.toolCall?.kind,
          options: params.options,
        });

        const allowOption = params.options.find(
          (o) => o.kind === "allow_once" || o.kind === "allow_always",
        );
        const selectedOptionId =
          allowOption?.optionId ?? params.options[0].optionId;

        const codeToolKind = params.toolCall?._meta?.codeToolKind;
        const isPlanApproval = params.toolCall?.kind === "switch_mode";

        // Relay questions to Slack when interaction originated there
        if (interactionOrigin === "slack") {
          if (codeToolKind === "question") {
            return this.buildSlackQuestionRelayResponse(
              payload,
              params.toolCall?._meta,
            );
          }
        }

        // Tools on relayed MCP servers execute on the user's machine with
        // their local privileges: always ask, regardless of permission mode
        // (docs/CLOUD-MCP-RELAY.md). Without a reachable client, deny rather
        // than auto-approve.
        {
          // Read the MCP server through the adapter-neutral `_meta.posthog`
          // channel (codex writes `_meta.posthog.mcp`, Claude writes the legacy
          // `_meta.claudeCode.toolName`; readMcpToolDescriptor handles both),
          // falling back to Claude's `rawInput.toolName`. Keying off only the
          // Claude channel would silently skip this gate for codex and let a
          // relayed tool auto-run in non-asking modes.
          const mcpServerName =
            this.readPermissionMcpDescriptor(params)?.server;
          // Codex reports the key the adapter registered the server under:
          // the raw name sanitized, plus a numeric suffix when another
          // server's name sanitized to the same base. The matcher accepts
          // every form the assignment can produce, because missing any of
          // them loses the relayed server's always-ask guarantee.
          if (
            mcpServerName &&
            (this.config.relayMcpServers ?? []).some((name) =>
              codexKeyMatchesMcpServerName(mcpServerName, name),
            )
          ) {
            if (mode !== "background" && this.hasReachableClient()) {
              return this.relayPermissionToClient(params);
            }
            return {
              outcome: { outcome: "cancelled" as const },
              _meta: {
                message:
                  "This tool runs on the user's machine via the MCP relay and " +
                  "requires their explicit approval, but no client is available " +
                  "to approve it. Do NOT retry; tell the user what you wanted to do.",
              },
            };
          }
        }

        const posthogExecSubTool =
          this.matchesPostHogExecPermissionRequest(params);
        if (mode !== "background" && posthogExecSubTool) {
          const isClaudeCodeRequest = Boolean(
            params.toolCall?._meta?.claudeCode,
          );
          const relayParams = {
            ...params,
            options: isClaudeCodeRequest
              ? params.options
              : params.options.filter(
                  (option) => option.kind !== "allow_always",
                ),
          };
          this.logger.debug("Relaying configured PostHog exec permission", {
            subTool: posthogExecSubTool,
            sessionPermissionMode: this.getSessionPermissionMode(),
          });
          return this.relayPermissionToClient(relayParams);
        }

        // Relay permission requests to the connected client when:
        // - Plan approvals: always relay because they gate autonomy changes
        //   that require human confirmation (buffered until desktop connects)
        // - Questions: relay when any client can receive and answer them
        // - Edit/bash in "default" mode: relay for manual approval
        // Other modes auto-approve. No client connected → auto-approve
        // (except plan approvals, which wait for a desktop, and questions,
        // which are parked for the user instead of being answered blindly).
        {
          const isQuestion = codeToolKind === "question";
          const sessionPermissionMode = this.getSessionPermissionMode();
          const needsDesktopApproval = this.shouldRelayPermissionToClient(
            sessionPermissionMode,
          );

          const hasReachableClient = this.hasReachableClient();

          // A background run has no human to answer a relayed approval
          // (hasDesktopConnected is true from the event-relay reader), so
          // auto-approve non-question permissions rather than hang on them.
          // Questions are parked (cancelled with message) below so the model
          // does not pick an answer on the user's behalf.
          if (
            mode !== "background" &&
            (isPlanApproval ||
              (isQuestion && hasReachableClient) ||
              (needsDesktopApproval && this.session?.hasDesktopConnected))
          ) {
            this.logger.debug("Relaying permission request", {
              kind: params.toolCall?.kind,
              isQuestion,
              hasDesktopConnected: this.session?.hasDesktopConnected ?? false,
              hasReachableClient,
              sessionPermissionMode,
            });
            return this.relayPermissionToClient(params);
          }

          // A question that cannot be relayed must never fall through to
          // auto-approve: the auto-selected option carries no answers, so the
          // tool would fail with "User did not provide answers" and the model
          // would answer on the user's behalf. Park it for the user instead.
          if (isQuestion) {
            return {
              outcome: { outcome: "cancelled" as const },
              _meta: {
                message:
                  "No user is available to answer this question right now. " +
                  "Do NOT pick an answer yourself and do NOT re-ask via this tool. " +
                  "Restate the question and its options in your response, then end " +
                  "your turn so the user can answer when they are back.",
              },
            };
          }
        }

        if (this.shouldBlockPublishPermission(params)) {
          return {
            outcome: { outcome: "cancelled" },
            _meta: {
              message:
                "This run is configured to stop before publishing. Do not push commits or create/update pull requests unless the user explicitly asks.",
            },
          };
        }

        return {
          outcome: {
            outcome: "selected" as const,
            optionId: selectedOptionId,
          },
        };
      },
      extNotification: async (
        method: string,
        params: Record<string, unknown>,
      ) => {
        this.logger.debug("Extension notification", { method, params });
      },
      sessionUpdate: async (params: {
        sessionId: string;
        update?: Record<string, unknown>;
      }) => {
        // Track permission mode changes for relay decisions
        if (
          params.update?.sessionUpdate === "current_mode_update" &&
          typeof params.update?.currentModeId === "string" &&
          this.session
        ) {
          this.session.permissionMode = params.update
            .currentModeId as PermissionMode;
          this.logger.debug("Permission mode updated", {
            mode: params.update.currentModeId,
          });
        }

        this.maybeAttachCreatedPr(payload, params.update);
      },
    };
  }

  private async relayAgentResponse(
    payload: JwtPayload,
    messageId?: string,
  ): Promise<void> {
    if (!this.session) {
      return;
    }

    if (this.questionRelayedToSlack) {
      this.questionRelayedToSlack = false;
      return;
    }

    try {
      await this.session.logWriter.flush(payload.run_id, { coalesce: true });
    } catch (error) {
      this.logger.debug("Failed to flush logs before Slack relay", {
        taskId: payload.task_id,
        runId: payload.run_id,
        error,
      });
    }

    const message = this.session.logWriter.getFullAgentResponse(payload.run_id);
    if (!message) {
      this.logger.debug("No agent message found for Slack relay", {
        taskId: payload.task_id,
        runId: payload.run_id,
        sessionRegistered: this.session.logWriter.isRegistered(payload.run_id),
      });
      return;
    }

    // Ordered assistant text blocks (one per message between tool calls).
    // The backend picks the last entry — the post-last-tool-use answer — so
    // Slack no longer sees the "Let me check…" narration. `message` stays as
    // the joined fallback for backends that don't understand `text_parts`.
    const messageParts = this.session.logWriter.getAgentResponseParts(
      payload.run_id,
    );

    try {
      await this.posthogAPI.relayMessage(
        payload.task_id,
        payload.run_id,
        message,
        messageParts,
        messageId,
      );
    } catch (error) {
      this.logger.debug("Failed to relay initial agent response to Slack", {
        taskId: payload.task_id,
        runId: payload.run_id,
        error,
      });
    }
  }

  private relaySlackQuestion(
    payload: JwtPayload,
    toolMeta: Record<string, unknown> | null | undefined,
  ): void {
    const firstQuestion = this.getFirstQuestionMeta(toolMeta);
    if (!this.isQuestionMeta(firstQuestion)) {
      return;
    }

    let message = `*${firstQuestion.question}*\n\n`;
    if (firstQuestion.options?.length) {
      firstQuestion.options.forEach(
        (opt: { label: string; description?: string }, i: number) => {
          message += `${i + 1}. *${opt.label}*`;
          if (opt.description) message += ` — ${opt.description}`;
          message += "\n";
        },
      );
    }
    message += "\nReply in this thread with your choice.";

    this.questionRelayedToSlack = true;
    this.posthogAPI
      .relayMessage(payload.task_id, payload.run_id, message)
      .catch((err) =>
        this.logger.debug("Failed to relay question to Slack", { err }),
      );
  }

  private getFirstQuestionMeta(
    toolMeta: Record<string, unknown> | null | undefined,
  ): unknown {
    if (!toolMeta) {
      return null;
    }

    const questionsValue = toolMeta.questions;
    if (!Array.isArray(questionsValue) || questionsValue.length === 0) {
      return null;
    }

    return questionsValue[0];
  }

  private isQuestionMeta(value: unknown): value is {
    question: string;
    options?: Array<{ label: string; description?: string }>;
  } {
    if (!value || typeof value !== "object") {
      return false;
    }

    const candidate = value as {
      question?: unknown;
      options?: unknown;
    };

    if (typeof candidate.question !== "string") {
      return false;
    }

    if (candidate.options === undefined) {
      return true;
    }

    if (!Array.isArray(candidate.options)) {
      return false;
    }

    return candidate.options.every(
      (option) =>
        !!option &&
        typeof option === "object" &&
        typeof (option as { label?: unknown }).label === "string",
    );
  }

  private maybeAttachCreatedPr(
    payload: JwtPayload,
    update: Record<string, unknown> | undefined,
  ): void {
    if (!update) return;
    for (const prUrl of findPrUrls(JSON.stringify(update))) {
      if (this.evaluatedPrUrls.has(prUrl)) continue;
      this.evaluatedPrUrls.add(prUrl);
      // Chain so attributions run in detection order; later PRs append after earlier ones.
      this.prAttributionChain = this.prAttributionChain
        .catch(() => {})
        .then(() => this.attachPrIfCreatedThisRun(payload, prUrl));
    }
  }

  private async attachPrIfCreatedThisRun(
    payload: JwtPayload,
    prUrl: string,
  ): Promise<void> {
    // Already the attributed PR (e.g. seeded from a Slack notification, or re-detected).
    if (prUrl === this.detectedPrUrl) return;

    let attribution: PrAttribution;
    let ghLogin: string | null;
    let checkout: OwnedBranch | null;
    let freshOutput: Record<string, unknown> | null;
    try {
      [attribution, ghLogin, checkout, freshOutput] = await Promise.all([
        this.fetchPrAttribution(prUrl),
        this.fetchGhLogin(),
        this.getCurrentCheckout(),
        this.posthogAPI
          .getTaskRun(payload.task_id, payload.run_id)
          .then((run) => run.output ?? null)
          .catch(() => null),
      ]);
    } catch (err) {
      this.logger.debug("PR attribution lookup failed", {
        runId: payload.run_id,
        prUrl,
        error: err,
      });
      return;
    }

    const ownedBranches = [
      ...(checkout ? [checkout] : []),
      ...ownedBranchesFromOutput(freshOutput),
    ];
    // GitHub App installation tokens (all cloud runs) can't read `gh api user`, so
    // ghLogin is null there and the head-branch match is what proves ownership.
    const owned = wasCreatedByThisRun({
      createdAt: attribution.createdAt,
      nowMs: Date.now(),
      author: attribution.author,
      ghLogin,
      prRepository: parsePrRepository(prUrl),
      headRefName: attribution.headRefName,
      isCrossRepository: attribution.isCrossRepository,
      ownedBranches,
      baseBranch: this.config.baseBranch ?? null,
    });
    if (!owned) {
      // Keep the evidence available for diagnosing wrongly rejected PRs without
      // surfacing every unrelated PR URL found in routine agent output.
      this.logger.debug(
        "PR seen in output is not this run's, skipping attribution",
        {
          runId: payload.run_id,
          prUrl,
          createdAt: attribution.createdAt,
          author: attribution.author,
          ghLogin,
          headRefName: attribution.headRefName,
          isCrossRepository: attribution.isCrossRepository,
          ownedBranches,
        },
      );
      return;
    }

    this.detectedPrUrl = prUrl;

    try {
      const urls = mergePrUrls(readPrUrls(freshOutput), [prUrl]);
      await this.posthogAPI.updateTaskRun(payload.task_id, payload.run_id, {
        output: buildPrOutput(freshOutput, urls),
      });
      this.logger.debug("Attributed created PR to task run", {
        taskId: payload.task_id,
        runId: payload.run_id,
        prUrl,
      });
    } catch (err) {
      this.logger.error("Failed to attach PR URL to task run", {
        taskId: payload.task_id,
        runId: payload.run_id,
        prUrl,
        error: err,
      });
    }
  }

  /** Env for a `gh` call that must run as the *current* actor. Prefers the live
   *  sandbox token (rewritten on an actor transition) over the process env
   *  (frozen at launch); returns undefined when unmanaged (local/desktop) so
   *  execGh falls back to the process env. */
  private ghActorEnv(): Record<string, string> | undefined {
    const token = resolveGithubToken();
    return token === undefined ? undefined : ghTokenEnv(token);
  }

  private async fetchPrAttribution(prUrl: string): Promise<PrAttribution> {
    const unknown: PrAttribution = {
      createdAt: null,
      author: null,
      headRefName: null,
      isCrossRepository: null,
    };
    const res = await execGh(
      [
        "pr",
        "view",
        prUrl,
        "--json",
        "createdAt,author,headRefName,isCrossRepository",
      ],
      {
        cwd: this.config.repositoryPath,
        timeoutMs: 10_000,
        env: this.ghActorEnv(),
      },
    );
    if (res.exitCode !== 0) return unknown;
    try {
      const data = JSON.parse(res.stdout) as {
        createdAt?: string;
        author?: { login?: string };
        headRefName?: string;
        isCrossRepository?: boolean;
      };
      return {
        createdAt: data.createdAt ?? null,
        author: data.author?.login ?? null,
        headRefName: data.headRefName ?? null,
        isCrossRepository:
          typeof data.isCrossRepository === "boolean"
            ? data.isCrossRepository
            : null,
      };
    } catch {
      return unknown;
    }
  }

  private ghLoginPromise: Promise<string | null> | null = null;
  private ghLoginToken: string | undefined;

  private fetchGhLogin(): Promise<string | null> {
    // Key the memoized login on the live token: an actor transition rebinds
    // /tmp/agent-env, so a cached login would otherwise attribute the new actor's
    // work to the previous one (or reject their PR).
    const token = resolveGithubToken();
    if (this.ghLoginPromise !== null && this.ghLoginToken === token) {
      return this.ghLoginPromise;
    }
    this.ghLoginToken = token;
    this.ghLoginPromise = execGh(["api", "user", "--jq", ".login"], {
      cwd: this.config.repositoryPath,
      timeoutMs: 10_000,
      env: token === undefined ? undefined : ghTokenEnv(token),
    })
      .then((res) => {
        const login = res.exitCode === 0 ? res.stdout.trim() : "";
        if (!login) this.ghLoginPromise = null;
        return login || null;
      })
      .catch(() => {
        this.ghLoginPromise = null;
        return null;
      });
    return this.ghLoginPromise;
  }

  private async cleanupSession({
    completeEventStream = false,
  }: {
    completeEventStream?: boolean;
  } = {}): Promise<void> {
    if (!this.session) return;

    this.logger.debug("Cleaning up session");

    try {
      await this.session.logWriter.flush(this.session.payload.run_id, {
        coalesce: true,
      });
    } catch (error) {
      this.logger.error("Failed to flush session logs", error);
    }

    if (this.mcpRelayServer) {
      await this.mcpRelayServer.stop();
      this.mcpRelayServer = null;
    }

    // Shutdown ends open spans and flushes batched records; without it,
    // sandbox teardown races the OTel batch delay and drops the tail of the
    // run's telemetry.
    try {
      await this.session.telemetry?.shutdown();
    } catch (error) {
      this.logger.error("Failed to shut down OTel run telemetry", error);
    }

    // Drain pending permissions before ACP cleanup to avoid deadlocks —
    // cleanup may await operations that are blocked on a permission response.
    for (const [, pending] of this.pendingPermissions) {
      pending.resolve({
        outcome: { outcome: "selected", optionId: "reject" },
        _meta: { customInput: "Session is shutting down." },
      });
    }
    this.pendingPermissions.clear();

    try {
      await this.session.acpConnection.cleanup();
    } catch (error) {
      this.logger.error("Failed to cleanup ACP connection", error);
    }

    if (this.session.sseController) {
      this.session.sseController.close();
    }

    if (completeEventStream) {
      await this.emitRtkSavings();
      await this.eventStreamSender?.stop();
    }

    this.pendingEvents = [];
    this.preSessionEvents = [];
    this.lastReportedBranch = null;
    // Run usage is per run: a later session on this instance (e.g. a resume
    // with a different run_id) must not inherit the previous run's totals.
    this.runUsage = new RunUsageAccumulator();
    this.session = null;
  }

  private async emitRtkSavings(): Promise<void> {
    if (!this.eventStreamSender || this.rtkSavingsAttempted) return;
    this.rtkSavingsAttempted = true;

    try {
      const savings = await (
        this.config.resolveRtkSavings ?? resolveRtkSavings
      )();
      if (!savings) return;

      this.eventStreamSender.enqueue({
        type: "notification",
        timestamp: new Date().toISOString(),
        notification: {
          jsonrpc: "2.0",
          method: POSTHOG_NOTIFICATIONS.RTK_SAVINGS,
          params: {
            task_id: this.config.taskId,
            run_id: this.config.runId,
            team_id: this.config.projectId,
            counter_id: this.config.taskId,
            cumulative_commands: savings.totalCommands,
            cumulative_input_tokens: savings.inputTokens,
            cumulative_output_tokens: savings.outputTokens,
            cumulative_tokens_saved: savings.tokensSaved,
            runtime_adapter: this.config.runtimeAdapter,
            model: this.config.model,
          },
        },
      });
    } catch (error) {
      this.logger.debug("Failed to emit rtk savings", { error });
    }
  }

  /**
   * Accumulates a settled turn's token usage into the run total and reports it
   * to the backend, merged into `TaskRun.state.token_usage`. Best-effort: a
   * reporting failure must never affect the turn outcome.
   */
  private recordTurnUsage(usage: PromptResponse["usage"]): void {
    if (!this.runUsage.add(usage)) return;
    const payload = this.session?.payload;
    if (!payload) return;
    void this.posthogAPI
      .updateTaskRun(payload.task_id, payload.run_id, {
        state: { token_usage: this.runUsage.snapshot() },
      })
      .catch((error) => {
        this.logger.warn("Failed to report run token usage", error);
      });
  }

  private handleAcpTransportMessage(message: unknown): void {
    if (isTurnCompleteNotification(message)) {
      if (this.suppressAdapterTurnComplete) {
        return;
      }
      this.adapterEmittedTurnComplete = true;
    }
    const event = {
      type: "notification",
      timestamp: new Date().toISOString(),
      notification: message,
    };
    if (!this.session) {
      this.preSessionEvents.push(event);
      return;
    }
    this.broadcastEvent(event);
  }

  private broadcastTurnComplete(stopReason: string): void {
    if (!this.session) return;
    if (this.adapterEmittedTurnComplete) {
      this.adapterEmittedTurnComplete = false;
      return;
    }
    const notification = {
      jsonrpc: "2.0",
      method: POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      params: {
        sessionId: this.session.acpSessionId,
        stopReason,
      },
    };

    this.broadcastEvent({
      type: "notification",
      timestamp: new Date().toISOString(),
      notification,
    });

    this.session.logWriter.appendRawLine(
      this.session.payload.run_id,
      JSON.stringify(notification),
    );
  }

  private broadcastEvent(event: Record<string, unknown>): void {
    this.eventStreamSender?.enqueue(event);

    if (this.session?.sseController) {
      this.sendSseEvent(this.session.sseController, event);
    } else {
      // Buffers events raised before a session exists yet (e.g. an MCP relay
      // request fired the instant the client subprocess starts, ahead of
      // `this.session` assignment) or before its SSE controller attaches.
      this.pendingEvents.push(event);
    }
  }

  private flushPreSessionEvents(): void {
    if (!this.session || this.preSessionEvents.length === 0) return;
    const events = this.preSessionEvents;
    this.preSessionEvents = [];
    for (const event of events) {
      this.broadcastEvent(event);
    }
  }

  private replayPendingEvents(): void {
    if (!this.session?.sseController || this.pendingEvents.length === 0) return;
    const events = this.pendingEvents;
    this.pendingEvents = [];
    for (const event of events) {
      this.sendSseEvent(this.session.sseController, event);
    }
  }

  private sendSseEvent(controller: SseController, data: unknown): void {
    try {
      controller.send(data);
    } catch {
      this.detachSseController(controller);
    }
  }

  /**
   * Relay a permission request (e.g., plan approval) to the connected desktop
   * app via SSE and wait for a response via the `/command` endpoint.
   *
   * The promise waits indefinitely — if SSE is disconnected, the event is
   * buffered by broadcastEvent and replayed when the client reconnects. Session
   * cleanup force-resolves all pending permissions, so there is no leak.
   */
  private relayPermissionToClient(params: {
    options: Array<{ kind: string; optionId: string; name?: string }>;
    toolCall?: Record<string, unknown> | null;
  }): Promise<{
    outcome: { outcome: "selected"; optionId: string };
    _meta?: Record<string, unknown>;
  }> {
    const requestId = crypto.randomUUID();
    const toolCallId = params.toolCall?.toolCallId as string | undefined;

    this.broadcastEvent({
      type: "permission_request",
      requestId,
      options: params.options,
      toolCall: params.toolCall,
    });

    // Persist the request so a client that connects after the live event can
    // recover the requestId from the log and re-surface the prompt.
    this.persistPermissionLifecycle(POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST, {
      requestId,
      toolCallId,
      options: params.options,
      toolCall: params.toolCall,
    });

    const toolCallMeta = params.toolCall?._meta as
      | { codeToolKind?: unknown }
      | undefined;
    return new Promise((resolve) => {
      this.pendingPermissions.set(requestId, {
        resolve,
        toolCallId,
        optionIds: new Set(params.options.map((option) => option.optionId)),
        validateOptionIds: toolCallMeta?.codeToolKind !== "question",
      });
    });
  }

  private persistPermissionLifecycle(
    method: string,
    params: Record<string, unknown>,
  ): void {
    if (!this.session) return;
    // appendRawLine wraps the line in the {type, timestamp, notification}
    // envelope, so pass the bare notification (matching broadcastTurnComplete).
    this.session.logWriter.appendRawLine(
      this.session.payload.run_id,
      JSON.stringify({ jsonrpc: "2.0", method, params }),
    );
  }

  private resolvePermission(
    requestId: string,
    optionId: string,
    customInput?: string,
    answers?: Record<string, string>,
  ): "resolved" | "not_found" | "invalid_option" {
    const pending = this.pendingPermissions.get(requestId);
    if (!pending) return "not_found";
    // The request stays parked and resolvable — a corrected response with an
    // offered option can still settle it.
    if (pending.validateOptionIds && !pending.optionIds.has(optionId)) {
      return "invalid_option";
    }

    this.pendingPermissions.delete(requestId);

    this.persistPermissionLifecycle(POSTHOG_NOTIFICATIONS.PERMISSION_RESOLVED, {
      requestId,
      toolCallId: pending.toolCallId,
      optionId,
    });

    const meta: Record<string, unknown> = {};
    if (customInput) meta.customInput = customInput;
    if (answers) meta.answers = answers;

    pending.resolve({
      outcome: { outcome: "selected" as const, optionId },
      ...(Object.keys(meta).length > 0 ? { _meta: meta } : {}),
    });
    return "resolved";
  }
}
