import type {
  Adapter,
  GitHandoffCheckpoint,
  HandoffLocalGitState as GitHandoffLocalGitState,
  PostHogAPIConfig,
} from "@posthog/shared";
import type { EffortLevel } from "@posthog/shared/domain-types";

export type {
  ArtifactType,
  PostHogAPIConfig,
  Task,
  TaskRun,
  TaskRunArtifact,
  TaskRunEnvironment,
  TaskRunStatus,
} from "@posthog/shared";

/**
 * Stored custom notification following ACP extensibility model.
 * Custom notifications use underscore-prefixed methods (e.g., `_posthog/phase_start`).
 * See: https://agentclientprotocol.com/docs/extensibility
 */
export interface StoredNotification {
  type: "notification";
  /** When this notification was stored */
  timestamp: string;
  /** JSON-RPC 2.0 notification (no id field = notification, not request) */
  notification: {
    jsonrpc: "2.0";
    method: string;
    params?: Record<string, unknown>;
  };
}

/**
 * Type alias for stored log entries.
 */
export type StoredEntry = StoredNotification;

export interface ProcessSpawnedCallback {
  onProcessSpawned?: (info: {
    pid: number;
    command: string;
    sessionId?: string;
  }) => void;
  onProcessExited?: (pid: number) => void;
  onMcpServersReady?: (serverNames: string[]) => void;
}

export interface TaskExecutionOptions {
  repositoryPath?: string;
  adapter?: Adapter;
  model?: string;
  gatewayUrl?: string;
  codexBinaryPath?: string;
  codexHome?: string;
  reasoningEffort?: EffortLevel;
  /**
   * Codex-only. Appended on top of the model's base prompt via the Codex
   * `developer_instructions` config key, preserving Codex's native base prompt.
   */
  developerInstructions?: string;
  processCallbacks?: ProcessSpawnedCallback;
  /** Callback invoked when the agent calls the create_output tool for structured output */
  onStructuredOutput?: (output: Record<string, unknown>) => Promise<void>;
  /** Additional directories the agent process can access beyond cwd. */
  additionalDirectories?: string[];
}

export type LogLevel = "debug" | "info" | "warn" | "error";

export type OnLogCallback = (
  level: LogLevel,
  scope: string,
  message: string,
  data?: unknown,
) => void;

/**
 * @deprecated Ignored. The in-process OTel log transport was removed; run
 * telemetry is exported by the agent server, configured via the
 * POSTHOG_AGENT_OTEL_LOGS_URL/_TOKEN environment variables. Kept only so
 * existing consumers keep compiling; will be removed in a future major.
 */
export interface OtelTransportConfig {
  /** PostHog ingest host, e.g., "https://us.i.posthog.com" */
  host: string;
  /** Project API key */
  apiKey: string;
  /** Override the logs endpoint path (default: /i/v1/logs) */
  logsPath?: string;
}

export interface AgentConfig {
  posthog?: PostHogAPIConfig;
  /** @deprecated Ignored — see {@link OtelTransportConfig}. */
  otelTransport?: OtelTransportConfig;
  /** Skip session log persistence (e.g. for preview sessions with no real task) */
  skipLogPersistence?: boolean;
  /** Local cache path for instant log loading (e.g., ~/.posthog-code) */
  localCachePath?: string;
  /**
   * Annotate files the agent reads with PostHog enrichment (event volume,
   * flag rollout/staleness, experiment links). Defaults to enabled when
   * `posthog` config is present; set `{ enabled: false }` to opt out.
   */
  enricher?: { enabled?: boolean };
  debug?: boolean;
  onLog?: OnLogCallback;
}

// Device info for tracking where work happens
export interface DeviceInfo {
  type: "local" | "cloud";
  name?: string;
}

// Agent execution mode - for tracking interactive vs background runs, when backgrounded an agent will continue working without asking questions
export type AgentMode = "interactive" | "background";

// Git file status codes
export type FileStatus = "A" | "M" | "D";

export interface FileChange {
  path: string;
  status: FileStatus;
}

export type HandoffLocalGitState = GitHandoffLocalGitState;

export interface GitCheckpoint extends GitHandoffCheckpoint {
  artifactPath?: string;
  indexArtifactPath?: string;
}

export interface GitCheckpointEvent extends GitCheckpoint {
  device?: DeviceInfo;
}

/**
 * Keeps the emitted `@posthog/agent/types` entrypoint as a runtime ESM module.
 *
 * `export {}` is stripped by tsup in this package, which leaves `dist/types.js`
 * empty and breaks downstream type resolution for the exported subpath.
 */
export const AGENT_TYPES_MODULE = true;
