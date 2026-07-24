import type {
  PromptResponse,
  SessionConfigOption,
  TerminalHandle,
  TerminalOutputResponse,
} from "@agentclientprotocol/sdk";
import type {
  McpSdkServerConfigWithInstance,
  Options,
  Query,
  SDKUserMessage,
} from "@anthropic-ai/claude-agent-sdk";
import type { PostHogProductId } from "../../posthog-products";
import type { AgentMode } from "../../types";
import type { Pushable } from "../../utils/streams";
import type { BaseSession } from "../base-acp-agent";
import type { ContextBreakdownBaseline } from "./context-breakdown";
import type { TaskState } from "./conversion/task-state";
import type { McpToolApprovals } from "./mcp/tool-metadata";
import type { SettingsManager } from "./session/settings";
import type { CodeExecutionMode } from "./tools";

export type EffortLevel = "low" | "medium" | "high" | "xhigh" | "max";

export type AccumulatedUsage = {
  inputTokens: number;
  outputTokens: number;
  cachedReadTokens: number;
  cachedWriteTokens: number;
};

export type BackgroundTerminal =
  | {
      handle: TerminalHandle;
      status: "started";
      lastOutput: TerminalOutputResponse | null;
    }
  | {
      status: "aborted" | "exited" | "killed" | "timedOut";
      pendingOutput: TerminalOutputResponse;
    };

/** One in-flight `prompt()` call, settled by the session's consumer. */
export type Turn = {
  promptUuid: string;
  pendingSteerUuids: Set<string>;
  isLocalOnlyCommand: boolean;
  commandName?: string;
  /** Invoked once at activation, matching the pre-consumer broadcast timing. */
  broadcast: () => Promise<void>;
  settled: boolean;
  resolve: (response: PromptResponse) => void;
  reject: (error: unknown) => void;
};

export type Session = BaseSession & {
  query: Query;
  /** The Options object passed to query() — mutating it affects subsequent prompts */
  queryOptions: Options;
  /** Rebuilds the in-process ("sdk") signed-commit server with a fresh instance
   * each call (reusing one throws "Already connected"); {} when none is enabled. */
  buildInProcessMcpServers: () => Record<
    string,
    McpSdkServerConfigWithInstance
  >;
  /** Names of the in-process servers registered at session start. Lets the
   * self-heal check status without rebuilding instances on every prompt. */
  localToolsServerNames: string[];
  input: Pushable<SDKUserMessage>;
  settingsManager: SettingsManager;
  permissionMode: CodeExecutionMode;
  /** Whether permission decisions are delegated to the cloud AgentServer. */
  cloudMode: boolean;
  posthogExecPermissionRegex?: RegExp;
  modeBeforePlan?: CodeExecutionMode;
  modelId?: string;
  cwd: string;
  taskRunId?: string;
  lastPlanFilePath?: string;
  lastPlanContent?: string;
  effort?: EffortLevel;
  /** User intent; retained while a non-fast model hides the "fast" option. */
  fastModeEnabled: boolean;
  /** Last title pushed via `session_info_update`, to dedupe turn-end polls. */
  lastTitle?: string;
  configOptions: SessionConfigOption[];
  accumulatedUsage: AccumulatedUsage;
  /** PostHog products used during this session, derived from MCP exec calls.
   *  Accumulates for the whole session (deduped); each newly-seen product is
   *  emitted immediately so the client can show a persistent, de-duplicated
   *  list. Never reset between turns. */
  sessionResources: Set<PostHogProductId>;
  /** Latest context window usage (total tokens from last assistant message) */
  contextUsed?: number;
  /** Context window size in tokens */
  contextSize?: number;
  /** Persists across prompt() calls so SDK-reported values survive turn boundaries */
  lastContextWindowSize?: number;
  /** FIFO of in-flight prompts; the SDK echoes them back in order. */
  turnQueue: Turn[];
  activeTurn: Turn | null;
  /** Echo-less results still owed by turns cancelled while queued. */
  pendingOrphanResults: number;
  consumer?: Promise<void>;
  /** Bumped by refreshSession so the retired consumer exits quietly. */
  queryGeneration: number;
  /** The query iterator ended and can't be revived; new prompts reject. */
  queryClosed?: boolean;
  cancelController?: AbortController;
  forceCancelTimer?: ReturnType<typeof setTimeout>;
  emitRawSDKMessages: boolean | SDKMessageFilter[];
  /** Refreshed at session init and on MCP/skill changes. */
  contextBreakdownBaseline?: ContextBreakdownBaseline;
  /**
   * Slash command names (without leading slash) the SDK recognizes for this
   * session — built-ins plus plugin/skill commands. Captured from the SDK's
   * init response. Used to distinguish "command produced no output" from
   * "command is genuinely unknown" when the session goes idle without an echo.
   */
  knownSlashCommands?: Set<string>;
  /**
   * Per-session task list accumulated from Task* tool calls.
   * SDK >=0.3.142 replaced TodoWrite (snapshot) with TaskCreate/TaskUpdate
   * (incremental, keyed by task id). Map iteration preserves insertion order
   * which we use for plan entry ordering.
   */
  taskState: TaskState;
};

export type ToolUseCache = {
  [key: string]: {
    type: "tool_use" | "server_tool_use" | "mcp_tool_use";
    id: string;
    name: string;
    input: unknown;
  };
};

/**
 * Per-content-block-index buffer for tool inputs streamed via
 * `input_json_delta` events. Keyed by the Anthropic content block index
 * (which resets per assistant message). Cleared on `content_block_stop`.
 */
export type ToolUseStreamCache = Map<
  number,
  { toolUseId: string; partialJson: string }
>;

export type TerminalInfo = {
  terminal_id: string;
};

export type TerminalOutput = {
  terminal_id: string;
  data: string;
};

export type TerminalExit = {
  terminal_id: string;
  exit_code: number | null;
  signal: string | null;
};

export type ToolUpdateMeta = {
  claudeCode?: {
    toolName: string;
    toolResponse?: unknown;
    parentToolCallId?: string;
    bashCommand?: string;
  };
  terminal_info?: TerminalInfo;
  terminal_output?: TerminalOutput;
  terminal_exit?: TerminalExit;
};

export type SDKMessageFilter = {
  type: string;
  subtype?: string;
};

export type NewSessionMeta = {
  taskRunId?: string;
  taskId?: string;
  environment?: "local" | "cloud";
  /**
   * Run mode. "background" means unattended (loops, durable ingest) — no human
   * drives the turns, so the agent may end its own run via the `finish` tool.
   * "interactive" runs are driven turn-by-turn and are ended by the human.
   */
  mode?: AgentMode;
  disableBuiltInTools?: boolean;
  systemPrompt?: unknown;
  sessionId?: string;
  permissionMode?: string;
  persistence?: { taskId?: string; runId?: string; logUrl?: string };
  additionalRoots?: string[];
  allowedDomains?: string[];
  /** Model ID to use for this session (e.g. "claude-sonnet-4-6") */
  model?: string;
  /** Base branch of the task's repo (e.g. "master"), for the signed-git tools. */
  baseBranch?: string;
  /**
   * Repo-less channel "generic chat box" session: enables the lazy-repo tools
   * (list_repos / clone_repo) and channel guidance. The agent decides at
   * runtime whether it needs a repo and clones one only if so.
   */
  channelMode?: boolean;
  /**
   * The user's spoken-narration setting at session start. Gates the speak
   * tool and its prompt instructions. Unset falls back by environment: cloud
   * emits always (consumers gate playback), local stays silent.
   */
  spokenNarration?: boolean;
  jsonSchema?: Record<string, unknown> | null;
  mcpToolApprovals?: McpToolApprovals;
  posthogExecPermissionRegex?: string;
  claudeCode?: {
    options?: Options;
    emitRawSDKMessages?: boolean | SDKMessageFilter[];
  };
};
