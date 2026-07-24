import type { Adapter } from "@posthog/shared";
import type { AgentMode } from "../types";
import type { RtkSavingsSummary } from "./rtk-savings";
import type { RemoteMcpServer } from "./schemas";

export interface ClaudeCodeConfig {
  systemPrompt?:
    | string
    | { type: "preset"; preset: "claude_code"; append?: string };
  plugins?: { type: "local"; path: string }[];
}

export interface AgentServerConfig {
  port: number;
  agentStateDir?: string;
  repositoryPath?: string;
  repoReadyFile?: string;
  apiUrl: string;
  apiKey: string;
  projectId: number;
  jwtPublicKey: string; // RS256 public key for JWT verification
  eventIngestToken?: string;
  // Base URL for the event-ingest POST only; falls back to apiUrl when unset.
  eventIngestBaseUrl?: string;
  eventIngestStreamWindowMs?: number;
  eventIngestKeepStreamOpen?: boolean;
  /** Full OTLP logs URL for run telemetry, e.g. https://us.i.posthog.com/i/v1/logs */
  otelLogsUrl?: string;
  /** Project API key for the OTLP logs/traces endpoints */
  otelLogsToken?: string;
  /** Full OTLP traces URL for run spans, e.g. https://us.i.posthog.com/i/v1/traces */
  otelTracesUrl?: string;
  mode: AgentMode;
  taskId: string;
  runId: string;
  createPr?: boolean;
  // User-opted auto-publish: push and open a draft PR on completion even for
  // manual (non-automated-origin) cloud runs. createPr=false still wins.
  autoPublish?: boolean;
  version?: string;
  mcpServers?: RemoteMcpServer[];
  /**
   * Case-insensitive JavaScript regex matched against PostHog `exec` sub-tool
   * names. Overrides the default approval regex for interactive calls.
   */
  posthogExecPermissionRegex?: string;
  /**
   * Names of desktop-only local MCP servers to expose through loopback relay
   * endpoints (docs/cloud-mcp-relay.md). Names only; the desktop resolves
   * each name against local config at execution time.
   */
  relayMcpServers?: string[];
  baseBranch?: string;
  claudeCode?: ClaudeCodeConfig;
  allowedDomains?: string[];
  runtimeAdapter?: Adapter;
  model?: string;
  reasoningEffort?: "low" | "medium" | "high" | "xhigh" | "max";
  resolveRtkSavings?: () => Promise<RtkSavingsSummary | null>;
}
