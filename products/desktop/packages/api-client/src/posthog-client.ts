import "./generated.augment";
import { isSupportedReasoningEffort } from "@posthog/agent/adapters/reasoning-effort";
import type {
  Adapter,
  CloudMcpServerImport,
  CloudMcpServerRelayDesignation,
  CloudRunSource,
  ExecutionMode,
  PrAuthorshipMode,
  SourceProduct,
  SourceType,
  StoredLogEntry,
  TaskRunArtifactMetadata,
} from "@posthog/shared";
import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  resolveCloudInitialPermissionMode,
} from "@posthog/shared";
import type {
  AgentAnalyticsData,
  AgentApplication,
  AgentApplicationSessionDetail,
  AgentApplicationSessionsListResponse,
  AgentApprovalRequest,
  AgentApprovalsListParams,
  AgentFleetLiveSessionsResponse,
  AgentMemoryFile,
  AgentMemorySearchResult,
  AgentMemoryTableHeader,
  AgentMemoryTableRows,
  AgentMemoryTreeNode,
  AgentPreviewToken,
  AgentRevision,
  AgentSessionEvent,
  AgentSessionLogEntry,
  AgentSessionLogsParams,
  AgentSessionsListParams,
  AgentSlackManifest,
  AgentSpec,
  AgentUsersListResponse,
  BundleFile,
  DecideApprovalRequest,
  DryRunToolEnvelope,
  DryRunToolRequest,
  DryRunToolResult,
  ModelCatalog,
  ToolCapabilities,
  ToolCompileError,
  WriteToolRequest,
  WriteToolResult,
} from "@posthog/shared/agent-platform-types";
import type {
  ActionabilityJudgmentArtefact,
  AvailableSuggestedReviewer,
  AvailableSuggestedReviewersResponse,
  ChannelFeedMessage,
  ChannelFeedMessageEvent,
  CodeReferenceArtefact,
  CommitArtefact,
  CommitDiffResponse,
  DismissalArtefact,
  LineReferenceArtefact,
  NoteArtefact,
  OrganizationMemberBasic,
  PriorityJudgmentArtefact,
  RepoSelectionArtefact,
  SafetyJudgmentArtefact,
  SandboxCustomImage,
  SandboxEnvironment,
  SandboxEnvironmentInput,
  Signal,
  SignalFindingArtefact,
  SignalProcessingStateResponse,
  SignalReport,
  SignalReportArtefact,
  SignalReportArtefactsResponse,
  SignalReportSignalsResponse,
  SignalReportStatus,
  SignalReportsQueryParams,
  SignalReportsResponse,
  SignalTeamConfig,
  SignalUserAutonomyConfig,
  SlackChannelsQueryParams,
  SlackChannelsResponse,
  SuggestedReviewersArtefact,
  SuggestedReviewerWriteEntry,
  Task,
  TaskChannel,
  TaskMention,
  TaskRun,
  TaskRunArtefact,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import {
  buildAgentAnalyticsQueries,
  type HogQLGrid,
  shapeAgentAnalytics,
} from "./agent-analytics";
import { buildApiFetcher, requestErrorStatus } from "./fetcher";
import { createApiClient, type Schemas } from "./generated";
import type { SpendAnalysisResponse } from "./spend-analysis";
export interface ApiClientLogger {
  warn(...args: unknown[]): void;
}

let log: ApiClientLogger = { warn: () => {} };

export function setPosthogApiClientLogger(logger: ApiClientLogger): void {
  log = logger;
}

// Host build version, set by the host at boot (default "unknown"); avoids a
// build-time global so the package typechecks standalone and across importers.
let clientAppVersion = "unknown";

export function setPosthogApiClientAppVersion(version: string): void {
  clientAppVersion = version;
}

export function getPosthogApiClientAppVersion(): string {
  return clientAppVersion;
}

export class SandboxCustomImagesDisabledError extends Error {
  constructor(message?: string) {
    super(message ?? "Custom sandbox images are not enabled");
    this.name = "SandboxCustomImagesDisabledError";
  }
}

export type UsageLimitType = "burst" | "sustained" | null;

// Stable message so callers recognize this after a saga reduces the error to a string.
export const CLOUD_USAGE_LIMIT_ERROR_MESSAGE = "Cloud usage limit reached";

export const SESSION_LOGS_MAX_PAGE_SIZE = 5000;

export interface TaskRunSessionLogsResult {
  entries: StoredLogEntry[];
  complete: boolean;
}

/** Thrown when the backend rejects a cloud run with a 429 usage-limit error. */
export class CloudUsageLimitError extends Error {
  limitType: UsageLimitType;
  resetAt: string | null;
  isPro: boolean;
  constructor(params: {
    limitType: UsageLimitType;
    resetAt: string | null;
    isPro: boolean;
  }) {
    super(CLOUD_USAGE_LIMIT_ERROR_MESSAGE);
    this.name = "CloudUsageLimitError";
    this.limitType = params.limitType;
    this.resetAt = params.resetAt;
    this.isPro = params.isPro;
  }
}

export const MCP_CATEGORIES = [
  { id: "all", label: "All" },
  { id: "business", label: "Business Operations" },
  { id: "data", label: "Data & Analytics" },
  { id: "design", label: "Design & Content" },
  { id: "dev", label: "Developer Tools & APIs" },
  { id: "infra", label: "Infrastructure" },
  { id: "productivity", label: "Productivity & Collaboration" },
] as const;

import type {
  McpApprovalState,
  McpAuthType,
  McpCategory,
  McpInstallationTool,
  McpRecommendedServer,
  McpServerInstallation,
} from "./types";
export type {
  McpApprovalState,
  McpAuthType,
  McpCategory,
  McpInstallationTool,
  McpRecommendedServer,
  McpServerInstallation,
};

export type Evaluation = Schemas.Evaluation;

export interface UserGitHubIntegration {
  id: string;
  kind: "github";
  installation_id: string;
  repository_selection?: string | null;
  account?: {
    type?: string | null;
    name?: string | null;
  } | null;
  uses_shared_installation?: boolean;
  created_at?: string;
}

export interface LlmSkillCreatedBy {
  id?: number;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
}

export interface LlmSkillFileManifest {
  path: string;
  content_type: string;
}

export interface LlmSkillFile {
  path: string;
  content: string;
  content_type: string;
}

export interface LlmSkillListItem {
  id: string;
  name: string;
  description: string;
  allowed_tools: unknown[];
  metadata: Record<string, unknown>;
  version: number;
  is_latest: boolean;
  latest_version?: number | null;
  version_count?: number | null;
  created_by: LlmSkillCreatedBy | null;
  created_at: string;
  updated_at: string;
}

export interface LlmSkill extends LlmSkillListItem {
  /** The SKILL.md markdown content. */
  body: string;
  /** Companion file manifest (paths only; fetch contents separately). */
  files: LlmSkillFileManifest[];
}

export interface LlmSkillFileInput {
  path: string;
  content: string;
  content_type?: string;
}

export interface SignalSourceConfig {
  id: string;
  source_product: SourceProduct;
  source_type: SourceType;
  enabled: boolean;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  status: "running" | "completed" | "failed" | null;
}

// ── Signals scouts ───────────────────────────────────────────────────────────
// Backend: posthog `products/signals/backend/scout_harness/views.py`.
// Endpoints live under /api/projects/{id}/signals/scout/ and require the
// `signal_scout:read` / `signal_scout:write` scopes.

export interface ScoutConfig {
  id: string;
  skill_name: string;
  enabled: boolean;
  /** False means dry-run: the scout runs but findings are not emitted. */
  emit: boolean;
  /**
   * Summary of what the scout investigates, from the skill's description
   * metadata. Empty string when the skill is absent or carries no description;
   * absent entirely on backends predating the field.
   */
  description?: string;
  /**
   * Where the scout came from: "canonical" for a scout PostHog ships and
   * maintains (seeded from products/signals/skills), "custom" for one a team
   * hand-authored. The serializer defaults to "custom" when the skill is absent;
   * the field itself is absent entirely on backends predating it.
   */
  scout_origin?: "canonical" | "custom";
  run_interval_minutes: number;
  last_run_at: string | null;
  created_at: string;
}

/** A team's enforced scout run caps and current usage, as dispatch applies them. */
export interface ScoutLimits {
  max_runs_per_tick: number;
  /** Null when the daily budget is uncapped. */
  max_runs_per_day: number | null;
  runs_today: number;
  /** Null when the daily budget is uncapped. */
  runs_remaining_today: number | null;
}

/**
 * Team-scoped scout metadata from the `signals-scout` flag: enrollment, an optional
 * announcement banner, and the enforced run limits. `banner_message` is null when unset.
 */
export interface ScoutMetadata {
  enrolled: boolean;
  banner_message: string | null;
  limits: ScoutLimits;
}

export interface ScoutRun {
  run_id: string;
  skill_name: string;
  skill_version: number;
  /** TaskRun-derived status, e.g. "completed" | "failed" | "in_progress" | "queued". */
  status: string;
  started_at: string | null;
  completed_at: string | null;
  task_id: string | null;
  task_run_id: string | null;
  /** Relative PostHog cloud path to the backing task run. */
  task_url: string | null;
  summary: string;
  emitted_count: number | null;
  emitted_finding_ids: string[];
}

export interface ScoutEmission {
  id: string;
  run_id: string;
  finding_id: string;
  description: string;
  weight: number;
  confidence: number;
  severity: string | null;
  /** Slug tags the scout attached to this finding (lowercase kebab-case, e.g. `cost-spike`). */
  tags?: string[];
  source_id: string;
  emitted_at: string;
}

/** Minimal inbox report projection paired with a scout finding by the reverse lookup. */
export interface LinkedSignalReport {
  id: string;
  title: string | null;
  status: SignalReportStatus;
}

/**
 * One scout finding paired with the inbox report (if any) its signal grouped into.
 * `report` is null when the finding hasn't grouped into a report yet, was
 * de-duplicated away, or its signal was deleted – the link is best effort.
 */
export interface ScoutEmissionReportLink {
  finding_id: string;
  source_id: string;
  report: LinkedSignalReport | null;
}

export interface ScoutScratchpadEntry {
  key: string;
  content: string;
  created_at: string;
  updated_at: string;
  created_by_run_id: string | null;
}

export interface ScoutRunsQueryParams {
  date_from?: string;
  date_to?: string;
  text?: string;
  emitted?: boolean;
  limit?: number;
}

export interface ExternalDataSourceSchema {
  id: string;
  name: string;
  should_sync: boolean;
  /** e.g. `full_refresh` (full table replication), `incremental`, `append` */
  sync_type?: string | null;
}

export interface ExternalDataSource {
  id: string;
  source_type: string;
  status: string;
  // The generated `ExternalDataSourceSerializers` types this as `string`,
  // but the actual API returns an array of schema objects
  schemas?: ExternalDataSourceSchema[] | string;
}

/**
 * Field-config variants for an external data source's connect form, as served
 * by the `external_data_sources/wizard/` endpoint. Mirrors PostHog Cloud's
 * `SourceFieldConfig` union (`posthog/schema.py`). The backend is the single
 * source of truth for which credential fields a source needs, so forms can be
 * rendered generically instead of hardcoded per source.
 */
export interface SourceFieldInputConfig {
  type:
    | "text"
    | "email"
    | "search"
    | "url"
    | "password"
    | "time"
    | "number"
    | "textarea";
  name: string;
  label: string;
  required: boolean;
  placeholder?: string;
  caption?: string | null;
  /** Redacted from API responses; render as a password field. */
  secret?: boolean;
}

export interface SourceFieldOauthConfig {
  type: "oauth";
  name: string;
  label: string;
  kind: string;
  required: boolean;
  requiredScopes?: string;
}

/**
 * A picker whose options are the accounts/resources a connected OAuth integration exposes (loaded
 * from the `oauth_accounts` endpoint using the integration's server-side token). Used e.g. for a
 * GitHub repository or an ad account.
 */
export interface SourceFieldOauthAccountSelectConfig {
  type: "oauth-account-select";
  name: string;
  label: string;
  /** Name of the sibling OAuth id field this selector reads its integration id from. */
  integrationField: string;
  /** Integration kind used to validate the connected integration, e.g. "github". */
  integrationKind: string;
  placeholder?: string;
  caption?: string;
  required?: boolean;
}

/** A selectable account/resource an OAuth integration exposes (shared `IntegrationAccount` shape). */
export interface IntegrationAccount {
  value: string;
  display_name: string;
  is_primary: boolean;
  badges: string[];
  group: string | null;
  secondary_text: string | null;
}

export interface SourceFieldSelectConfigOption {
  label: string;
  value: string;
  fields?: SourceFieldConfig[];
}

export interface SourceFieldSelectConfig {
  type: "select";
  name: string;
  label: string;
  required: boolean;
  defaultValue?: string;
  options: SourceFieldSelectConfigOption[];
}

export interface SourceFieldSwitchGroupConfig {
  type: "switch-group";
  name: string;
  label: string;
  caption?: string;
  default?: boolean;
  fields: SourceFieldConfig[];
}

/** Field types the generic renderer does not (yet) handle inline. */
export interface SourceFieldUnsupportedConfig {
  type: "ssh-tunnel" | "file-upload";
  name: string;
  label: string;
}

export type SourceFieldConfig =
  | SourceFieldInputConfig
  | SourceFieldOauthConfig
  | SourceFieldOauthAccountSelectConfig
  | SourceFieldSelectConfig
  | SourceFieldSwitchGroupConfig
  | SourceFieldUnsupportedConfig;

export interface SourceConfig {
  name: string;
  label?: string;
  caption?: string;
  fields: SourceFieldConfig[];
}

export interface FolderInstructionsUser {
  id?: number;
  uuid?: string;
  first_name?: string;
  last_name?: string | null;
  email?: string;
}

export interface FolderInstructions {
  id: string;
  content: string;
  version: number;
  is_latest: boolean;
  created_by: FolderInstructionsUser | null;
  created_at: string;
  updated_at: string;
}

export interface FolderInstructionsVersion {
  id: string;
  version: number;
  is_latest: boolean;
  created_by: FolderInstructionsUser | null;
  created_at: string;
}

interface PaginatedFolderInstructionsVersions {
  count: number;
  next: string | null;
  previous: string | null;
  results: FolderInstructionsVersion[];
}

// Thrown when PUT /instructions/ rejects a publish because the caller's
// `base_version` is older than the current latest. Callers can re-fetch and
// retry against the new latest.
export class FolderInstructionsConflictError extends Error {
  status = 409;
  constructor(
    message = "Folder instructions changed since you started editing",
  ) {
    super(message);
    this.name = "FolderInstructionsConflictError";
  }
}

export interface TaskArtifactUploadRequest {
  name: string;
  type: "user_attachment" | "skill_bundle";
  size: number;
  content_type?: string;
  source?: string;
  metadata?: TaskRunArtifactMetadata;
}

export interface DirectUploadPresignedPost {
  url: string;
  fields: Record<string, string>;
}

export interface PreparedTaskArtifactUpload extends TaskArtifactUploadRequest {
  id: string;
  storage_path: string;
  expires_in: number;
  presigned_post: DirectUploadPresignedPost;
}

export interface FinalizedTaskArtifactUpload {
  id: string;
  name: string;
  type: string;
  source?: string;
  size?: number;
  content_type?: string;
  metadata?: TaskArtifactUploadRequest["metadata"];
  storage_path: string;
  uploaded_at?: string;
}

interface CloudRunOptions {
  adapter?: Adapter;
  model?: string;
  reasoningLevel?: string;
  sandboxEnvironmentId?: string;
  customImageId?: string;
  prAuthorshipMode?: PrAuthorshipMode;
  autoPublish?: boolean;
  /** Only false is sent: opts the run out of rtk command-output compression. */
  rtkEnabled?: boolean;
  runSource?: CloudRunSource;
  signalReportId?: string;
  initialPermissionMode?: ExecutionMode;
  /**
   * Local url-based MCP servers to make available inside the sandbox. The
   * backend merges these into the agent server's `--mcpServers` at spawn.
   */
  importedMcpServers?: CloudMcpServerImport[];
  relayedMcpServers?: CloudMcpServerRelayDesignation[];
}

interface CreateTaskRunOptions extends CloudRunOptions {
  environment?: "local" | "cloud";
  mode?: "interactive" | "background";
  branch?: string | null;
}

interface StartTaskRunOptions {
  pendingUserMessage?: string;
  pendingUserArtifactIds?: string[];
}

function buildCloudRunRequestBody(
  options?: CloudRunOptions & {
    branch?: string | null;
    mode?: "interactive" | "background";
    resumeFromRunId?: string;
    pendingUserMessage?: string;
    pendingUserArtifactIds?: string[];
  },
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    mode: options?.mode ?? "interactive",
  };

  if (options?.branch) {
    body.branch = options.branch;
  }
  if (options?.adapter) {
    body.runtime_adapter = options.adapter;
    if (options.model) {
      body.model = options.model;
    }
    if (options.reasoningLevel) {
      if (!options.model) {
        throw new Error(
          "A cloud reasoning level requires a model to be selected.",
        );
      }
      if (
        !isSupportedReasoningEffort(
          options.adapter,
          options.model,
          options.reasoningLevel,
        )
      ) {
        throw new Error(
          `Reasoning effort '${options.reasoningLevel}' is not supported for ${options.adapter} model '${options.model}'.`,
        );
      }
      body.reasoning_effort = options.reasoningLevel;
    }
    // The API rejects initial_permission_mode without runtime_adapter and validates it per adapter.
    if (options.initialPermissionMode) {
      body.initial_permission_mode = resolveCloudInitialPermissionMode(
        options.adapter,
        options.initialPermissionMode,
      );
    }
  }
  if (options?.resumeFromRunId) {
    body.resume_from_run_id = options.resumeFromRunId;
  }
  if (options?.pendingUserMessage) {
    body.pending_user_message = options.pendingUserMessage;
  }
  if (options?.pendingUserArtifactIds?.length) {
    body.pending_user_artifact_ids = options.pendingUserArtifactIds;
  }
  if (options?.sandboxEnvironmentId) {
    body.sandbox_environment_id = options.sandboxEnvironmentId;
  }
  if (options?.customImageId) {
    body.custom_image_id = options.customImageId;
  }
  if (options?.prAuthorshipMode) {
    body.pr_authorship_mode = options.prAuthorshipMode;
  }
  if (options?.autoPublish) {
    body.auto_publish = options.autoPublish;
  }
  if (options?.rtkEnabled === false) {
    body.rtk_enabled = false;
  }
  if (options?.runSource) {
    body.run_source = options.runSource;
  }
  if (options?.signalReportId) {
    body.signal_report_id = options.signalReportId;
  }
  if (options?.importedMcpServers?.length) {
    body.imported_mcp_servers = options.importedMcpServers;
  }
  if (options?.relayedMcpServers?.length) {
    body.relayed_mcp_servers = options.relayedMcpServers;
  }

  return body;
}

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/** Unwrap the shared fetcher's `Failed request: [<status>] <json>` into the endpoint's clean message. */
function extractRequestErrorMessage(error: unknown, fallback: string): string {
  const raw = error instanceof Error ? error.message : String(error);
  const match = raw.match(/^Failed request: \[(\d+)\] (.*)$/s);
  if (!match) {
    return fallback;
  }
  try {
    const body = JSON.parse(match[2]) as { error?: unknown; detail?: unknown };
    const message = body.error ?? body.detail;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  } catch {
    // Non-JSON body — fall through to the status-based fallback.
  }
  return `${fallback} (HTTP ${match[1]})`;
}

/**
 * Parse the shared fetcher's `Failed request: [<status>] <json-body>` throw back
 * into its status + parsed JSON body, so status-specific responses (422, 429,
 * 500, 503) can be handled as data instead of a generic error. Returns null when
 * the error isn't that shape (e.g. a network failure).
 */
function parseFailedRequest(
  error: unknown,
): { status: number; body: unknown } | null {
  const raw = error instanceof Error ? error.message : String(error);
  const match = raw.match(/^Failed request: \[(\d+)\] (.*)$/s);
  if (!match) {
    return null;
  }
  let body: unknown;
  try {
    body = JSON.parse(match[2]);
  } catch {
    body = match[2];
  }
  return { status: Number(match[1]), body };
}

type AnyArtefact =
  | SignalReportArtefact
  | PriorityJudgmentArtefact
  | ActionabilityJudgmentArtefact
  | SafetyJudgmentArtefact
  | SignalFindingArtefact
  | RepoSelectionArtefact
  | SuggestedReviewersArtefact
  | DismissalArtefact
  | CodeReferenceArtefact
  | LineReferenceArtefact
  | CommitArtefact
  | TaskRunArtefact
  | NoteArtefact;

const DISMISSAL_REASONS = new Set<DismissalReasonOptionValue>(
  DISMISSAL_REASON_OPTIONS.map((o) => o.value),
);

const PRIORITY_VALUES = new Set(["P0", "P1", "P2", "P3", "P4"]);

function normalizePriorityJudgmentArtefact(
  value: Record<string, unknown>,
): PriorityJudgmentArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;

  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue) return null;

  const priority = optionalString(contentValue.priority);
  if (!priority || !PRIORITY_VALUES.has(priority)) return null;

  return {
    id,
    type: "priority_judgment",
    ...artefactBase(value),
    content: {
      explanation: optionalString(contentValue.explanation) ?? "",
      priority: priority as PriorityJudgmentArtefact["content"]["priority"],
    },
  };
}

const ACTIONABILITY_VALUES = new Set([
  "immediately_actionable",
  "requires_human_input",
  "not_actionable",
]);

function normalizeActionabilityJudgmentArtefact(
  value: Record<string, unknown>,
): ActionabilityJudgmentArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;

  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue) return null;

  // Support both agentic ("actionability") and legacy ("choice") field names
  const actionability =
    optionalString(contentValue.actionability) ??
    optionalString(contentValue.choice);
  if (!actionability || !ACTIONABILITY_VALUES.has(actionability)) return null;

  return {
    id,
    type: "actionability_judgment",
    ...artefactBase(value),
    content: {
      explanation: optionalString(contentValue.explanation) ?? "",
      actionability:
        actionability as ActionabilityJudgmentArtefact["content"]["actionability"],
      already_addressed:
        typeof contentValue.already_addressed === "boolean"
          ? contentValue.already_addressed
          : false,
    },
  };
}

function normalizeSafetyJudgmentArtefact(
  value: Record<string, unknown>,
): SafetyJudgmentArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;

  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue || typeof contentValue.choice !== "boolean") return null;

  return {
    id,
    type: "safety_judgment",
    ...artefactBase(value),
    content: {
      choice: contentValue.choice,
      explanation: optionalString(contentValue.explanation),
    },
  };
}

function normalizeSignalFindingArtefact(
  value: Record<string, unknown>,
): SignalFindingArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;

  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue) return null;

  const signalId = optionalString(contentValue.signal_id);
  if (!signalId) return null;

  return {
    id,
    type: "signal_finding",
    ...artefactBase(value),
    content: {
      signal_id: signalId,
      relevant_code_paths: Array.isArray(contentValue.relevant_code_paths)
        ? contentValue.relevant_code_paths.filter(
            (p: unknown): p is string => typeof p === "string",
          )
        : [],
      relevant_commit_hashes: isObjectRecord(
        contentValue.relevant_commit_hashes,
      )
        ? Object.fromEntries(
            Object.entries(contentValue.relevant_commit_hashes).filter(
              (e): e is [string, string] => typeof e[1] === "string",
            ),
          )
        : {},
      data_queried: optionalString(contentValue.data_queried) ?? "",
      verified:
        typeof contentValue.verified === "boolean"
          ? contentValue.verified
          : false,
    },
  };
}

function normalizeRepoSelectionArtefact(
  value: Record<string, unknown>,
): RepoSelectionArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;

  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue) return null;

  return {
    id,
    type: "repo_selection",
    ...artefactBase(value),
    content: {
      repository: optionalString(contentValue.repository),
      reason: optionalString(contentValue.reason) ?? "",
    },
  };
}

function normalizeDismissalArtefact(
  value: Record<string, unknown>,
): DismissalArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;

  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue) return null;

  const rawReason = optionalString(contentValue.reason);
  const reason =
    rawReason && DISMISSAL_REASONS.has(rawReason as DismissalReasonOptionValue)
      ? (rawReason as DismissalReasonOptionValue)
      : null;

  if (reason == null) {
    return null;
  }

  return {
    id,
    type: "dismissal",
    ...artefactBase(value),
    content: {
      reason,
      note: optionalString(contentValue.note) ?? "",
      user_id:
        typeof contentValue.user_id === "number" ? contentValue.user_id : null,
      user_uuid: optionalString(contentValue.user_uuid),
    },
  };
}

// ── Log artefact normalizers ──────────────────────────────────────────────
// The backend stores log-artefact content as a JSON object (not the string-or-
// session_id shape the generic fallback expects), so each type needs an explicit
// normalizer — otherwise it falls through and gets dropped.

/** User the artefact is attributed to, when the row carries a valid `created_by`. */
function normalizeArtefactUser(value: unknown): UserBasic | null {
  if (!isObjectRecord(value)) return null;
  const id = value.id;
  const uuid = optionalString(value.uuid);
  const email = optionalString(value.email);
  if (typeof id !== "number" || !uuid || !email) return null;
  return {
    id,
    uuid,
    email,
    first_name: optionalString(value.first_name) ?? undefined,
    last_name: optionalString(value.last_name) ?? undefined,
  };
}

/** Row-level fields shared by every artefact: timestamps plus user/task attribution. */
function artefactBase(value: Record<string, unknown>): {
  created_at: string;
  updated_at: string | null;
  created_by: UserBasic | null;
  task_id: string | null;
} {
  return {
    created_at: optionalString(value.created_at) ?? new Date(0).toISOString(),
    updated_at: optionalString(value.updated_at),
    created_by: normalizeArtefactUser(value.created_by),
    task_id: optionalString(value.task_id),
  };
}

function normalizeCodeReferenceArtefact(
  value: Record<string, unknown>,
): CodeReferenceArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;
  const c = isObjectRecord(value.content) ? value.content : null;
  if (!c) return null;
  const file_path = optionalString(c.file_path);
  if (!file_path) return null;

  return {
    id,
    type: "code_reference",
    ...artefactBase(value),
    content: {
      file_path,
      start_line: typeof c.start_line === "number" ? c.start_line : 0,
      end_line: typeof c.end_line === "number" ? c.end_line : 0,
      contents: optionalString(c.contents) ?? "",
      relevance_note: optionalString(c.relevance_note) ?? "",
    },
  };
}

function normalizeLineReferenceArtefact(
  value: Record<string, unknown>,
): LineReferenceArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;
  const c = isObjectRecord(value.content) ? value.content : null;
  if (!c) return null;
  const file_path = optionalString(c.file_path);
  if (!file_path) return null;

  return {
    id,
    type: "line_reference",
    ...artefactBase(value),
    content: {
      file_path,
      line: typeof c.line === "number" ? c.line : 0,
      note: optionalString(c.note) ?? "",
      contents: optionalString(c.contents),
    },
  };
}

function normalizeCommitArtefact(
  value: Record<string, unknown>,
): CommitArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;
  const c = isObjectRecord(value.content) ? value.content : null;
  if (!c) return null;
  const repository = optionalString(c.repository);
  const branch = optionalString(c.branch);
  const commit_sha = optionalString(c.commit_sha);
  if (!repository || !branch || !commit_sha) return null;

  return {
    id,
    type: "commit",
    ...artefactBase(value),
    content: {
      repository,
      branch,
      commit_sha,
      message: optionalString(c.message) ?? "",
      note: optionalString(c.note),
    },
  };
}

function normalizeTaskRunArtefact(
  value: Record<string, unknown>,
): TaskRunArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;
  const c = isObjectRecord(value.content) ? value.content : null;
  if (!c) return null;
  const task_id = optionalString(c.task_id);
  if (!task_id) return null;
  const product = optionalString(c.product);
  const type = optionalString(c.type);
  if (!product || !type) return null;

  return {
    id,
    type: "task_run",
    ...artefactBase(value),
    content: {
      task_id,
      run_id: optionalString(c.run_id),
      product,
      type,
    },
  };
}

function normalizeNoteArtefact(
  value: Record<string, unknown>,
): NoteArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;
  const c = isObjectRecord(value.content) ? value.content : null;
  if (!c) return null;
  const note = optionalString(c.note);
  if (!note) return null;

  return {
    id,
    type: "note",
    ...artefactBase(value),
    content: {
      note,
      author: optionalString(c.author),
    },
  };
}

/** Best human-readable one-liner from arbitrary artefact content. */
function contentPreview(content: unknown): string {
  if (typeof content === "string") return content;
  if (isObjectRecord(content)) {
    for (const key of ["note", "explanation", "reason", "message", "content"]) {
      const v = content[key];
      if (typeof v === "string" && v.trim()) return v;
    }
  }
  try {
    const text = JSON.stringify(content);
    return text && text !== "{}" && text !== "null" ? text.slice(0, 300) : "";
  } catch {
    return "";
  }
}

/**
 * Last-resort normalizer: keeps the row (type, timestamps, attribution, a text
 * preview) when its content doesn't match the type's expected shape, so an
 * artefact never silently vanishes from the activity log.
 */
function normalizeFallbackArtefact(
  value: Record<string, unknown>,
): SignalReportArtefact | null {
  const id = optionalString(value.id);
  if (!id) return null;
  return {
    id,
    type: optionalString(value.type) ?? "unknown",
    degraded: true,
    ...artefactBase(value),
    content: {
      session_id: "",
      start_time: "",
      end_time: "",
      distinct_id: "",
      content: contentPreview(value.content),
      distance_to_centroid: null,
    },
  };
}

function normalizeSignalReportArtefact(value: unknown): AnyArtefact | null {
  if (!isObjectRecord(value)) {
    return null;
  }

  const dispatchType = optionalString(value.type);
  if (dispatchType === "signal_finding") {
    return (
      normalizeSignalFindingArtefact(value) ?? normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "actionability_judgment") {
    return (
      normalizeActionabilityJudgmentArtefact(value) ??
      normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "safety_judgment") {
    return (
      normalizeSafetyJudgmentArtefact(value) ?? normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "priority_judgment") {
    return (
      normalizePriorityJudgmentArtefact(value) ??
      normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "repo_selection") {
    return (
      normalizeRepoSelectionArtefact(value) ?? normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "dismissal") {
    return (
      normalizeDismissalArtefact(value) ?? normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "code_reference") {
    return (
      normalizeCodeReferenceArtefact(value) ?? normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "line_reference") {
    return (
      normalizeLineReferenceArtefact(value) ?? normalizeFallbackArtefact(value)
    );
  }
  if (dispatchType === "commit") {
    return normalizeCommitArtefact(value) ?? normalizeFallbackArtefact(value);
  }
  if (dispatchType === "task_run") {
    return normalizeTaskRunArtefact(value) ?? normalizeFallbackArtefact(value);
  }
  if (dispatchType === "note") {
    return normalizeNoteArtefact(value) ?? normalizeFallbackArtefact(value);
  }

  const id = optionalString(value.id);
  if (!id) {
    return null;
  }

  const type = dispatchType ?? "unknown";

  // suggested_reviewers: content is an array of reviewer objects
  if (type === "suggested_reviewers" && Array.isArray(value.content)) {
    return {
      id,
      type: "suggested_reviewers" as const,
      ...artefactBase(value),
      content: value.content as SuggestedReviewersArtefact["content"],
    };
  }

  // video_segment and other artefacts with object content
  const contentValue = isObjectRecord(value.content) ? value.content : null;
  if (!contentValue) {
    return normalizeFallbackArtefact(value);
  }

  const content = optionalString(contentValue.content);
  const sessionId = optionalString(contentValue.session_id);

  // The backend may return empty content objects when binary decode fails.
  if (!content && !sessionId) {
    return normalizeFallbackArtefact(value);
  }

  return {
    id,
    type,
    ...artefactBase(value),
    content: {
      session_id: sessionId ?? "",
      start_time: optionalString(contentValue.start_time) ?? "",
      end_time: optionalString(contentValue.end_time) ?? "",
      distinct_id: optionalString(contentValue.distinct_id) ?? "",
      content: content ?? "",
      distance_to_centroid:
        typeof contentValue.distance_to_centroid === "number"
          ? contentValue.distance_to_centroid
          : null,
    },
  };
}

function parseSignalReportArtefactsPayload(
  value: unknown,
): SignalReportArtefactsResponse {
  const payload = isObjectRecord(value) ? value : null;
  const rawResults = Array.isArray(payload?.results)
    ? payload.results
    : Array.isArray(value)
      ? value
      : [];

  const results = rawResults
    .map(normalizeSignalReportArtefact)
    .filter((artefact): artefact is AnyArtefact => artefact !== null);
  const count =
    typeof payload?.count === "number" ? payload.count : results.length;

  if (rawResults.length > 0 && results.length === 0) {
    return {
      results: [],
      count: 0,
      unavailableReason: "invalid_payload",
    };
  }

  return {
    results,
    count,
  };
}

function normalizeAvailableSuggestedReviewer(
  uuid: string,
  value: unknown,
): AvailableSuggestedReviewer | null {
  if (!isObjectRecord(value)) {
    return null;
  }

  const normalizedUuid = optionalString(uuid);
  if (!normalizedUuid) {
    return null;
  }

  return {
    uuid: normalizedUuid,
    name: optionalString(value.name) ?? "",
    email: optionalString(value.email) ?? "",
    github_login: optionalString(value.github_login) ?? "",
  };
}

function parseAvailableSuggestedReviewersPayload(
  value: unknown,
): AvailableSuggestedReviewersResponse {
  if (!isObjectRecord(value)) {
    return {
      results: [],
      count: 0,
    };
  }

  const results = Object.entries(value)
    .map(([uuid, reviewer]) =>
      normalizeAvailableSuggestedReviewer(uuid, reviewer),
    )
    .filter(
      (reviewer): reviewer is AvailableSuggestedReviewer => reviewer !== null,
    );

  return {
    results,
    count: results.length,
  };
}

/**
 * Wraps the ingress preview token in the `parameters.header` shape the fetcher
 * merges into request headers without clobbering the auth bearer. Returns
 * `undefined` when there is no token so unmodified ingress calls stay byte-for-
 * byte identical to today.
 */
function previewTokenHeader(
  token: string | null | undefined,
): { header: { "X-Agent-Preview-Token": string } } | undefined {
  return token ? { header: { "X-Agent-Preview-Token": token } } : undefined;
}

export class PostHogAPIClient {
  private api: ReturnType<typeof createApiClient>;
  private _teamId: number | null = null;

  constructor(
    apiHost: string,
    getAccessToken: () => Promise<string>,
    refreshAccessToken: () => Promise<string>,
    teamId?: number,
  ) {
    const baseUrl = apiHost.endsWith("/") ? apiHost.slice(0, -1) : apiHost;
    this.api = createApiClient(
      buildApiFetcher({
        getAccessToken,
        refreshAccessToken,
        appVersion: clientAppVersion,
      }),
      baseUrl,
    );
    if (teamId) {
      this._teamId = teamId;
    }
  }

  setTeamId(teamId: number | null | undefined): void {
    this._teamId = teamId ?? null;
  }

  private async getTeamId(): Promise<number> {
    if (this._teamId !== null) {
      return this._teamId;
    }

    const user = await this.api.get("/api/users/{uuid}/", {
      path: { uuid: "@me" },
    });

    if (user?.team?.id) {
      this._teamId = user.team.id;
      return this._teamId;
    }

    throw new Error("No team found for user");
  }

  async getCurrentUser() {
    const data = await this.api.get("/api/users/{uuid}/", {
      path: { uuid: "@me" },
    });
    return data;
  }

  // Desktop file system — the backend surface that backs canvas channels
  // (top-level folders) and dashboards. These routes aren't in the generated
  // OpenAPI client, so we use the raw fetcher.
  // Channels are top-level folders on the desktop file system. Filtering to
  // `type=folder` server-side (and requesting a large page) keeps us from
  // paginating over every dashboard and filed task just to populate the
  // sidebar channel list — the bulk of the initial-load cost otherwise.
  async getDesktopFileSystemChannels(): Promise<Schemas.FileSystem[]> {
    const DESKTOP_FILE_SYSTEM_MAX_PAGES = 50;
    const DESKTOP_FILE_SYSTEM_PAGE_SIZE = 200;
    const teamId = await this.getTeamId();
    const all: Schemas.FileSystem[] = [];
    let urlPath: string = `/api/projects/${teamId}/desktop_file_system/?type=folder&limit=${DESKTOP_FILE_SYSTEM_PAGE_SIZE}`;
    for (let i = 0; i < DESKTOP_FILE_SYSTEM_MAX_PAGES; i++) {
      const url = new URL(`${this.api.baseUrl}${urlPath}`);
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: urlPath,
      });
      if (!response.ok) {
        throw new Error(
          `Failed to fetch desktop file system channels: ${response.statusText}`,
        );
      }
      const page = (await response.json()) as Schemas.PaginatedFileSystemList;
      all.push(...page.results);
      if (!page.next) return all;
      const nextUrl = new URL(page.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    log.warn(
      `getDesktopFileSystemChannels hit MAX_PAGES (${DESKTOP_FILE_SYSTEM_MAX_PAGES}); returning partial results`,
      { returned: all.length },
    );
    return all;
  }

  // Create a top-level channel (a folder row whose path is a single segment).
  async createDesktopFileSystemChannel(
    name: string,
  ): Promise<Schemas.FileSystem> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify({ path: name, type: "folder", depth: 1 }),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to create desktop file system channel: ${response.statusText}`,
      );
    }
    return (await response.json()) as Schemas.FileSystem;
  }

  // Rename a top-level channel: PATCH its path (a single segment) to the new
  // name. The backend recomputes depth from the path.
  async renameDesktopFileSystemChannel(
    id: string,
    name: string,
  ): Promise<Schemas.FileSystem> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(id)}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify({ path: name }),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to rename desktop file system channel: ${response.statusText}`,
      );
    }
    return (await response.json()) as Schemas.FileSystem;
  }

  // Delete a desktop file system entry by id (used to remove top-level channels).
  async deleteDesktopFileSystem(id: string): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(id)}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to delete desktop file system channel: ${response.statusText}`,
      );
    }
  }

  // Desktop file system shortcuts — the user-scoped "starred" items on the
  // desktop surface (e.g. starred channels). Unlike the file system rows above,
  // shortcuts are per-user, so they back cross-device starring without leaking
  // one user's stars to their teammates. Not in the generated OpenAPI client,
  // so we use the raw fetcher.
  async getDesktopFileSystemShortcuts(): Promise<Schemas.FileSystemShortcut[]> {
    const SHORTCUTS_MAX_PAGES = 50;
    const SHORTCUTS_PAGE_SIZE = 200;
    const teamId = await this.getTeamId();
    const all: Schemas.FileSystemShortcut[] = [];
    let urlPath: string = `/api/projects/${teamId}/desktop_file_system_shortcut/?limit=${SHORTCUTS_PAGE_SIZE}`;
    for (let i = 0; i < SHORTCUTS_MAX_PAGES; i++) {
      const url = new URL(`${this.api.baseUrl}${urlPath}`);
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: urlPath,
      });
      if (!response.ok) {
        throw new Error(
          `Failed to fetch desktop file system shortcuts: ${response.statusText}`,
        );
      }
      const page =
        (await response.json()) as Schemas.PaginatedFileSystemShortcutList;
      all.push(...page.results);
      if (!page.next) return all;
      const nextUrl = new URL(page.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    log.warn(
      `getDesktopFileSystemShortcuts hit MAX_PAGES (${SHORTCUTS_MAX_PAGES}); returning partial results`,
      { returned: all.length },
    );
    return all;
  }

  // Create a desktop shortcut for the current user. For a folder/channel the
  // backend links by `ref` (the folder's full path), with `path` as the label.
  async createDesktopFileSystemShortcut(input: {
    path: string;
    type: string;
    ref?: string;
    href?: string;
  }): Promise<Schemas.FileSystemShortcut> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system_shortcut/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(input),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to create desktop file system shortcut: ${response.statusText}`,
      );
    }
    return (await response.json()) as Schemas.FileSystemShortcut;
  }

  // Delete a desktop shortcut by id (used to unstar). A 404 means it's already
  // gone, which is the desired end state, so we treat it as success.
  async deleteDesktopFileSystemShortcut(id: string): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system_shortcut/${encodeURIComponent(id)}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to delete desktop file system shortcut: ${response.statusText}`,
      );
    }
  }

  // Per-folder, versioned markdown instructions for a desktop folder. The
  // endpoint is keyed on the FileSystem row id (must be `type === "folder"`).
  // Returns the current latest version or null when none has been published.
  async getDesktopFolderInstructions(
    folderId: string,
  ): Promise<FolderInstructions | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(folderId)}/instructions/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (response.status === 404) return null;
    if (!response.ok) {
      throw new Error(
        `Failed to fetch folder instructions: ${response.statusText}`,
      );
    }
    return (await response.json()) as FolderInstructions;
  }

  // Publish a new version of the folder's instructions. Pass `base_version`
  // (the latest version the editor was started from) for optimistic
  // concurrency; use 0 when no instructions exist yet. A 409 turns into a
  // typed `FolderInstructionsConflictError` so the UI can prompt to reload.
  async putDesktopFolderInstructions(
    folderId: string,
    input: { content: string; base_version?: number },
  ): Promise<FolderInstructions> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(folderId)}/instructions/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "put",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(input),
      },
    });
    if (response.status === 409) {
      throw new FolderInstructionsConflictError();
    }
    if (!response.ok) {
      throw new Error(
        `Failed to publish folder instructions: ${response.statusText}`,
      );
    }
    return (await response.json()) as FolderInstructions;
  }

  // Soft-delete all versions of this folder's instructions. The folder row
  // itself is not affected.
  async deleteDesktopFolderInstructions(folderId: string): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(folderId)}/instructions/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to delete folder instructions: ${response.statusText}`,
      );
    }
  }

  // List version metadata (no content) newest-first. Single page is enough for
  // the typical UI; we cap follow-up pages to avoid runaway pagination on
  // pathological histories.
  async listDesktopFolderInstructionVersions(
    folderId: string,
  ): Promise<FolderInstructionsVersion[]> {
    const VERSIONS_MAX_PAGES = 20;
    const teamId = await this.getTeamId();
    const all: FolderInstructionsVersion[] = [];
    let urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(folderId)}/instructions/versions/`;
    for (let i = 0; i < VERSIONS_MAX_PAGES; i++) {
      const url = new URL(`${this.api.baseUrl}${urlPath}`);
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: urlPath,
      });
      if (!response.ok) {
        throw new Error(
          `Failed to fetch folder instruction versions: ${response.statusText}`,
        );
      }
      const page =
        (await response.json()) as PaginatedFolderInstructionsVersions;
      all.push(...page.results);
      if (!page.next) return all;
      const nextUrl = new URL(page.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    log.warn(
      `listDesktopFolderInstructionVersions hit MAX_PAGES (${VERSIONS_MAX_PAGES}); returning partial results`,
      { folderId, returned: all.length },
    );
    return all;
  }

  // The task currently generating this folder's CONTEXT.md, shared across the
  // project so any user sees an in-progress generation (instead of fragile
  // local state). Keyed on the folder row (which always exists), not the
  // instructions object (which doesn't until the first version is published).
  // Returns null when nothing is generating — or, until the backend ships this
  // endpoint, on 404 (the feature degrades to no shared indicator).
  async getDesktopFolderGenerationTask(
    folderId: string,
  ): Promise<string | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(folderId)}/context_generation/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (response.status === 404) return null;
    if (!response.ok) {
      throw new Error(
        `Failed to fetch folder generation task: ${response.statusText}`,
      );
    }
    const data = (await response.json()) as { task_id?: string | null };
    return data.task_id ?? null;
  }

  // Record (or clear, with null) the task generating this folder's CONTEXT.md.
  async setDesktopFolderGenerationTask(
    folderId: string,
    taskId: string | null,
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/desktop_file_system/${encodeURIComponent(folderId)}/context_generation/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "put",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify({ task_id: taskId }),
      },
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to set folder generation task: ${response.statusText}`,
      );
    }
  }

  async getGithubLogin(): Promise<string | null> {
    const data = (await this.api.get("/api/users/{uuid}/github_login/", {
      path: { uuid: "@me" },
    })) as { github_login: string | null };
    return data.github_login;
  }

  /**
   * `POST .../integrations/github/start/`. Optional `teamId` matches app project when session `current_team` differs.
   */
  async startGithubUserIntegrationConnect(teamId?: number): Promise<{
    install_url: string;
    connect_flow?: "oauth_authorize" | "oauth_discover" | "app_install";
  }> {
    const id = teamId ?? (await this.getTeamId());
    const urlPath = `/api/users/@me/integrations/github/start/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify({ team_id: id, connect_from: "posthog_code" }),
      },
    });
    if (!response.ok) {
      const err = (await response.json().catch(() => ({}))) as {
        detail?: unknown;
      };
      const detail =
        typeof err.detail === "string"
          ? err.detail
          : "Failed to start GitHub connection";
      throw new Error(detail);
    }
    return (await response.json()) as {
      install_url: string;
      connect_flow?: "oauth_authorize" | "oauth_discover" | "app_install";
    };
  }

  async getGithubUserIntegrations(): Promise<UserGitHubIntegration[]> {
    const urlPath = `/api/users/@me/integrations/?kind=github`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch personal GitHub integrations: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      results?: UserGitHubIntegration[];
    };
    return data.results ?? [];
  }

  async disconnectGithubUserIntegration(installationId: string): Promise<void> {
    const urlPath = `/api/users/@me/integrations/github/${encodeURIComponent(installationId)}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to disconnect GitHub integration: ${response.statusText}`,
      );
    }
  }

  async switchOrganization(orgId: string): Promise<void> {
    await this.api.patch("/api/users/{uuid}/", {
      path: { uuid: "@me" },
      body: { set_current_organization: orgId } as Record<string, unknown>,
    });
  }

  async approveAiDataProcessing(): Promise<void> {
    const urlPath = `/api/organizations/@current/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify({ is_ai_data_processing_approved: true }),
      },
    });
  }

  async getProject(projectId: number) {
    //@ts-expect-error this is not in the generated client
    const data = await this.api.get("/api/projects/{project_id}/", {
      path: { project_id: projectId.toString() },
    });
    return data as Schemas.Team;
  }

  async listSignalSourceConfigs(
    projectId: number,
  ): Promise<SignalSourceConfig[]> {
    const urlPath = `/api/projects/${projectId}/signals/source_configs/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch signal source configs: ${response.statusText}`,
      );
    }
    const data = (await response.json()) as
      | { results: SignalSourceConfig[] }
      | SignalSourceConfig[];
    return Array.isArray(data) ? data : (data.results ?? []);
  }

  async createSignalSourceConfig(
    projectId: number,
    options: {
      source_product: SignalSourceConfig["source_product"];
      source_type: SignalSourceConfig["source_type"];
      enabled: boolean;
      config?: Record<string, unknown>;
    },
  ): Promise<SignalSourceConfig> {
    const urlPath = `/api/projects/${projectId}/signals/source_configs/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(options),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to create signal source config: ${response.statusText}`,
      );
    }
    return (await response.json()) as SignalSourceConfig;
  }

  async updateSignalSourceConfig(
    projectId: number,
    configId: string,
    updates: { enabled: boolean },
  ): Promise<SignalSourceConfig> {
    const urlPath = `/api/projects/${projectId}/signals/source_configs/${configId}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(updates),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to update signal source config: ${response.statusText}`,
      );
    }
    return (await response.json()) as SignalSourceConfig;
  }

  private async scoutGet<T>(
    projectId: number,
    subPath: string,
    query?: Record<string, string | number | boolean | undefined>,
  ): Promise<T> {
    const urlPath = `/api/projects/${projectId}/signals/scout/${subPath}`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Scout request failed (${subPath}): ${response.statusText}`,
      );
    }
    return (await response.json()) as T;
  }

  private async scoutPost<T>(
    projectId: number,
    subPath: string,
    body: unknown,
  ): Promise<T> {
    const urlPath = `/api/projects/${projectId}/signals/scout/${subPath}`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(body),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Scout request failed (${subPath}): ${response.statusText}`,
      );
    }
    return (await response.json()) as T;
  }

  async listScoutConfigs(projectId: number): Promise<ScoutConfig[]> {
    const data = await this.scoutGet<
      { results: ScoutConfig[] } | ScoutConfig[]
    >(projectId, "configs/");
    return Array.isArray(data) ? data : (data.results ?? []);
  }

  async getScoutMetadata(projectId: number): Promise<ScoutMetadata> {
    return this.scoutGet<ScoutMetadata>(projectId, "metadata/current/");
  }

  async updateScoutConfig(
    projectId: number,
    configId: string,
    updates: {
      enabled?: boolean;
      emit?: boolean;
      run_interval_minutes?: number;
    },
  ): Promise<ScoutConfig> {
    const urlPath = `/api/projects/${projectId}/signals/scout/configs/${configId}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(updates),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to update scout config: ${response.statusText}`,
      );
    }
    return (await response.json()) as ScoutConfig;
  }

  async listScoutRuns(
    projectId: number,
    params?: ScoutRunsQueryParams,
  ): Promise<ScoutRun[]> {
    const data = await this.scoutGet<{ results: ScoutRun[] } | ScoutRun[]>(
      projectId,
      "runs/",
      {
        date_from: params?.date_from,
        date_to: params?.date_to,
        text: params?.text,
        emitted: params?.emitted,
        limit: params?.limit,
      },
    );
    return Array.isArray(data) ? data : (data.results ?? []);
  }

  async getScoutRun(projectId: number, runId: string): Promise<ScoutRun> {
    return await this.scoutGet<ScoutRun>(projectId, `runs/${runId}/`);
  }

  /**
   * POST a run-id list to a scout batch endpoint and flatten the response. The
   * API caps each call at SCOUT_BATCH_RUN_ID_LIMIT ids, so larger lists are
   * split into parallel chunks and concatenated — the caller never has to know
   * the cap exists. Run ids belonging to another team contribute no rows rather
   * than erroring, so a single stale id can't blank the list.
   */
  private async scoutBatchByRunIds<T>(
    projectId: number,
    subPath: string,
    runIds: string[],
  ): Promise<T[]> {
    if (runIds.length === 0) return [];
    const SCOUT_BATCH_RUN_ID_LIMIT = 200;
    const chunks: string[][] = [];
    for (let i = 0; i < runIds.length; i += SCOUT_BATCH_RUN_ID_LIMIT) {
      chunks.push(runIds.slice(i, i + SCOUT_BATCH_RUN_ID_LIMIT));
    }
    const pages = await Promise.all(
      chunks.map((chunk) =>
        this.scoutPost<{ results: T[] } | T[]>(projectId, subPath, {
          run_ids: chunk,
        }),
      ),
    );
    return pages.flatMap((data) =>
      Array.isArray(data) ? data : (data.results ?? []),
    );
  }

  /**
   * Every supplied run's emitted findings in one request, flattened newest-first
   * (each row keeps its `run_id` so the caller can regroup). Replaces the old
   * per-run fan-out — one Postgres query instead of one request per run.
   */
  async batchScoutRunEmissions(
    projectId: number,
    runIds: string[],
  ): Promise<ScoutEmission[]> {
    return this.scoutBatchByRunIds<ScoutEmission>(
      projectId,
      "runs/emissions/batch/",
      runIds,
    );
  }

  /**
   * Best-effort reverse lookup: for each finding the supplied runs emitted, the
   * inbox report (if any) its underlying signal grouped into. Resolves every
   * run's findings in a single ClickHouse round-trip instead of one per run.
   * Pairs with the report's evidence list, which links the other direction.
   */
  async batchScoutEmissionReports(
    projectId: number,
    runIds: string[],
  ): Promise<ScoutEmissionReportLink[]> {
    return this.scoutBatchByRunIds<ScoutEmissionReportLink>(
      projectId,
      "runs/emissions/reports/batch/",
      runIds,
    );
  }

  async searchScoutScratchpad(
    projectId: number,
    params?: { text?: string; limit?: number },
  ): Promise<ScoutScratchpadEntry[]> {
    const data = await this.scoutGet<
      { results: ScoutScratchpadEntry[] } | ScoutScratchpadEntry[]
    >(projectId, "scratchpad/", {
      text: params?.text,
      limit: params?.limit,
    });
    return Array.isArray(data) ? data : (data.results ?? []);
  }

  async listEvaluations(projectId: number): Promise<Evaluation[]> {
    const data = await this.api.get(
      "/api/environments/{project_id}/evaluations/",
      {
        path: { project_id: projectId.toString() },
        query: { limit: 200 },
      },
    );
    return data.results ?? [];
  }

  async updateEvaluation(
    projectId: number,
    evaluationId: string,
    updates: { enabled: boolean },
  ): Promise<Evaluation> {
    return await this.api.patch(
      "/api/environments/{project_id}/evaluations/{id}/",
      {
        path: {
          project_id: projectId.toString(),
          id: evaluationId,
        },
        body: updates,
      },
    );
  }

  async listExternalDataSources(
    projectId: number,
  ): Promise<ExternalDataSource[]> {
    const data = (await this.api.get(
      "/api/projects/{project_id}/external_data_sources/",
      {
        path: { project_id: projectId.toString() },
        query: {},
      },
    )) as unknown as { results?: ExternalDataSource[] } | ExternalDataSource[];
    return Array.isArray(data) ? data : (data.results ?? []);
  }

  async createExternalDataSource(
    projectId: number,
    payload: {
      source_type: string;
      payload: Record<string, unknown>;
    },
  ): Promise<ExternalDataSource> {
    const response = await this.api.post(
      "/api/projects/{project_id}/external_data_sources/",
      {
        path: { project_id: projectId.toString() },
        body: payload as unknown as Schemas.ExternalDataSourceCreate,
        withResponse: true,
        throwOnStatusError: false,
      },
    );
    if (!response.ok) {
      const errorData = isObjectRecord(response.data)
        ? (response.data as { detail?: string })
        : {};
      throw new Error(
        errorData.detail ??
          `Failed to create external data source: ${response.statusText}`,
      );
    }
    return response.data as unknown as ExternalDataSource;
  }

  /**
   * Fetch the connect-form field schema for external data source types from the
   * warehouse wizard endpoint. Pass `sourceType` (e.g. `"Jira"`) to scope to one
   * source; omit to fetch every source's config. Returns a map keyed by the
   * capitalized source type string.
   */
  async getExternalDataSourceConfigs(
    projectId: number,
    sourceType?: string,
  ): Promise<Record<string, SourceConfig>> {
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${projectId}/external_data_sources/wizard/`,
    );
    if (sourceType) {
      url.searchParams.set("source_type", sourceType);
    }
    const path = `/api/environments/${projectId}/external_data_sources/wizard/`;
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    if (!response.ok) {
      throw new Error(`Failed to fetch source configs: ${response.statusText}`);
    }
    return (await response.json()) as Record<string, SourceConfig>;
  }

  /**
   * List the accounts/resources a connected OAuth integration exposes for a source type (e.g. the
   * repositories a GitHub integration can access), for an `oauth-account-select` field. The backend
   * uses the integration's stored token; the client only passes the integration id. Pass `search`
   * to filter server-side for large lists.
   */
  async getOauthAccounts(
    projectId: number,
    sourceType: string,
    integrationId: number | string,
    search?: string,
  ): Promise<IntegrationAccount[]> {
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${projectId}/external_data_sources/oauth_accounts/`,
    );
    url.searchParams.set("source_type", sourceType);
    url.searchParams.set("integration_id", String(integrationId));
    if (search?.trim()) {
      url.searchParams.set("search", search.trim());
    }
    const path = `/api/environments/${projectId}/external_data_sources/oauth_accounts/`;
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    if (!response.ok) {
      throw new Error(`Failed to fetch accounts: ${response.statusText}`);
    }
    const data = (await response.json()) as { accounts?: IntegrationAccount[] };
    return data.accounts ?? [];
  }

  async updateExternalDataSchema(
    projectId: number,
    schemaId: string,
    updates: { should_sync: boolean; sync_type?: string },
  ): Promise<void> {
    const urlPath = `/api/projects/${projectId}/external_data_schemas/${schemaId}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify(updates),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to update external data schema: ${response.statusText}`,
      );
    }
  }

  async getTasks(options?: {
    repository?: string;
    createdBy?: number;
    originProduct?: string;
    internal?: boolean;
    channel?: string;
  }) {
    const teamId = await this.getTeamId();
    const params: Record<string, string | number | boolean> = {
      limit: 500,
    };

    if (options?.repository) {
      params.repository = options.repository;
    }

    if (options?.createdBy) {
      params.created_by = options.createdBy;
    }

    if (options?.originProduct) {
      params.origin_product = options.originProduct;
    }

    if (options?.internal) {
      params.internal = true;
    }

    if (options?.channel) {
      params.channel = options.channel;
    }

    const data = await this.api.get(`/api/projects/{project_id}/tasks/`, {
      path: { project_id: teamId.toString() },
      query: params,
    });

    return data.results ?? [];
  }

  async getTaskSummaries(ids: string[]) {
    if (ids.length === 0) return [];
    const TASK_SUMMARIES_MAX_PAGES = 50;
    const teamId = await this.getTeamId();
    const all: Schemas.TaskSummary[] = [];
    let urlPath: string = `/api/projects/${teamId}/tasks/summaries/`;
    for (let i = 0; i < TASK_SUMMARIES_MAX_PAGES; i++) {
      const url = new URL(`${this.api.baseUrl}${urlPath}`);
      const response = await this.api.fetcher.fetch({
        method: "post",
        url,
        path: urlPath,
        overrides: {
          body: JSON.stringify({ ids } satisfies Schemas.TaskSummariesRequest),
        },
      });
      if (!response.ok) {
        throw new Error(
          `Failed to fetch task summaries: ${response.statusText}`,
        );
      }
      const page = (await response.json()) as Schemas.PaginatedTaskSummaryList;
      all.push(...page.results);
      if (!page.next) return all;
      const nextUrl = new URL(page.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    log.warn(
      `getTaskSummaries hit MAX_PAGES (${TASK_SUMMARIES_MAX_PAGES}); returning partial results`,
      { ids: ids.length, returned: all.length },
    );
    return all;
  }

  async getTask(taskId: string): Promise<Task> {
    const teamId = await this.getTeamId();
    const data = await this.api.get(`/api/projects/{project_id}/tasks/{id}/`, {
      path: { project_id: teamId.toString(), id: taskId },
    });
    return data as unknown as Task;
  }

  async createTask(
    options: Pick<Task, "description"> &
      Partial<
        Pick<
          Task,
          | "title"
          | "repository"
          | "json_schema"
          | "origin_product"
          | "runtime"
          | "signal_report"
        >
      > & {
        github_integration?: number | null;
        github_user_integration?: string | null;
        branch?: string | null;
        runtime_adapter?: string | null;
        model?: string | null;
        reasoning_effort?: string | null;
        channel?: string | null;
        pending_user_message?: string;
        pending_user_artifact_ids?: string[];
        auto_publish?: boolean;
      },
  ) {
    const teamId = await this.getTeamId();
    const { origin_product: originProduct, ...taskOptions } = options;

    const data = await this.api.post(`/api/projects/{project_id}/tasks/`, {
      path: { project_id: teamId.toString() },
      body: {
        ...taskOptions,
        origin_product: originProduct ?? "user_created",
      } as unknown as Schemas.Task,
    });

    return data;
  }

  async updateTask(taskId: string, updates: Partial<Schemas.Task>) {
    const teamId = await this.getTeamId();
    const data = await this.api.patch(
      `/api/projects/{project_id}/tasks/{id}/`,
      {
        path: { project_id: teamId.toString(), id: taskId },
        body: updates,
      },
    );

    return data;
  }

  async deleteTask(taskId: string) {
    const teamId = await this.getTeamId();
    await this.api.delete(`/api/projects/{project_id}/tasks/{id}/`, {
      path: { project_id: teamId.toString(), id: taskId },
    });
  }

  async duplicateTask(taskId: string) {
    const task = await this.getTask(taskId);
    return this.createTask({
      description: task.description ?? "",
      title: task.title,
      repository: task.repository,
      json_schema: task.json_schema,
      origin_product: task.origin_product,
      github_integration: task.github_integration,
      github_user_integration: task.github_user_integration,
    });
  }

  // Task channels + threads. Not in the generated OpenAPI client yet, so these
  // go through the raw fetcher like the desktop file-system endpoints above.

  // List backend task channels: all public channels plus the requester's
  // personal "#me" channel (provisioned lazily server-side on first list).
  async getTaskChannels(): Promise<TaskChannel[]> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/`;
    const response = await this.api.fetcher.fetch({
      method: "get",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch task channels: ${response.statusText}`);
    }
    return (await response.json()) as TaskChannel[];
  }

  // Resolve-or-create a public channel by name (idempotent server-side).
  async resolveTaskChannel(name: string): Promise<TaskChannel> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({ name }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to resolve task channel: ${response.statusText}`);
    }
    return (await response.json()) as TaskChannel;
  }

  // A channel's system-announcement feed (context created, CONTEXT.md being
  // built), chronological. Durable + team-visible, rendered alongside task cards.
  async getChannelFeed(channelId: string): Promise<ChannelFeedMessage[]> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${channelId}/feed/`;
    const response = await this.api.fetcher.fetch({
      method: "get",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch channel feed: ${response.statusText}`);
    }
    return (await response.json()) as ChannelFeedMessage[];
  }

  // Post a system announcement into a channel's feed. The row is authored by the
  // system; the server records the requester as `author` for "Adam …" rendering.
  async postChannelFeedMessage(
    channelId: string,
    input: {
      event: ChannelFeedMessageEvent;
      payload?: Record<string, unknown>;
      // Optional explicit timestamp (ISO) so a burst of announcements orders
      // deterministically instead of racing on server insert time.
      createdAt?: string;
    },
  ): Promise<ChannelFeedMessage> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${channelId}/feed/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: {
        body: JSON.stringify({
          event: input.event,
          payload: input.payload ?? {},
          ...(input.createdAt ? { created_at: input.createdAt } : {}),
        }),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to post channel feed message: ${response.statusText}`,
      );
    }
    return (await response.json()) as ChannelFeedMessage;
  }

  // Mentions of the current user across task threads, newest first.
  async getTaskMentions(options?: { since?: string }): Promise<TaskMention[]> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_mentions/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    if (options?.since) {
      url.searchParams.set("since", options.since);
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch task mentions: ${response.statusText}`);
    }
    return (await response.json()) as TaskMention[];
  }

  async getTaskThreadMessages(taskId: string): Promise<TaskThreadMessage[]> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/thread_messages/`;
    const response = await this.api.fetcher.fetch({
      method: "get",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch thread messages: ${response.statusText}`,
      );
    }
    return (await response.json()) as TaskThreadMessage[];
  }

  async createTaskThreadMessage(
    taskId: string,
    content: string,
  ): Promise<TaskThreadMessage> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/thread_messages/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({ content }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to post thread message: ${response.statusText}`);
    }
    return (await response.json()) as TaskThreadMessage;
  }

  async deleteTaskThreadMessage(
    taskId: string,
    messageId: string,
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/thread_messages/${encodeURIComponent(messageId)}/`;
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to delete thread message: ${response.statusText}`,
      );
    }
  }

  // Forward a thread message into the task's live run. Task author only; the
  // backend rejects with 400/403 otherwise (surfaced via the error body detail).
  async sendTaskThreadMessageToAgent(
    taskId: string,
    messageId: string,
  ): Promise<TaskThreadMessage> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/thread_messages/${encodeURIComponent(messageId)}/send_to_agent/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({}) },
    });
    if (!response.ok) {
      const errorText = await response.text().catch(() => "");
      let message = `Failed to send message to agent: ${response.statusText}`;
      try {
        const parsed = JSON.parse(errorText) as { detail?: string };
        if (parsed.detail) message = parsed.detail;
      } catch {
        if (errorText) message = errorText;
      }
      throw new Error(message);
    }
    return (await response.json()) as TaskThreadMessage;
  }

  // Everyone in the current organization — the pool of taggable teammates for
  // thread @-mentions. Membership churn is slow, so callers cache aggressively.
  async listOrganizationMembers(): Promise<OrganizationMemberBasic[]> {
    const result = await this.listOrganizationMembersWithStatus();
    return result.members;
  }

  async listOrganizationMembersWithStatus(): Promise<{
    members: OrganizationMemberBasic[];
    isComplete: boolean;
  }> {
    const ORG_MEMBERS_MAX_PAGES = 20;
    const ORG_MEMBERS_PAGE_SIZE = 200;
    const all: OrganizationMemberBasic[] = [];
    let urlPath = `/api/organizations/@current/members/?limit=${ORG_MEMBERS_PAGE_SIZE}`;
    for (let i = 0; i < ORG_MEMBERS_MAX_PAGES; i++) {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url: new URL(`${this.api.baseUrl}${urlPath}`),
        path: urlPath,
      });
      if (!response.ok) {
        throw new Error(
          `Failed to fetch organization members: ${response.statusText}`,
        );
      }
      const page = (await response.json()) as {
        results: OrganizationMemberBasic[];
        next: string | null;
      };
      all.push(...page.results);
      if (!page.next) return { members: all, isComplete: true };
      const nextUrl = new URL(page.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    log.warn(
      `listOrganizationMembers hit MAX_PAGES (${ORG_MEMBERS_MAX_PAGES}); returning partial results`,
      { returned: all.length },
    );
    return { members: all, isComplete: false };
  }

  async sendRunCommand(
    taskId: string,
    runId: string,
    method: "user_message" | "cancel" | "close",
    params?: Record<string, unknown>,
  ): Promise<{ success: boolean; result?: unknown; error?: string }> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/command/`,
    );
    const body = {
      jsonrpc: "2.0",
      method,
      params: params ?? {},
      id: `posthog-code-${Date.now()}`,
    };

    try {
      const response = await this.api.fetcher.fetch({
        method: "post",
        url,
        path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/command/`,
        overrides: {
          body: JSON.stringify(body),
        },
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => "");
        let errorMessage = `Command failed: ${response.statusText}`;
        try {
          const errorJson = JSON.parse(errorText);
          errorMessage =
            errorJson.error?.message ?? errorJson.error ?? errorMessage;
        } catch {
          if (errorText) errorMessage = errorText;
        }
        return { success: false, error: errorMessage };
      }

      const data = (await response.json()) as {
        error?: { message?: string };
        result?: unknown;
      };
      if (data.error) {
        return {
          success: false,
          error: data.error.message ?? JSON.stringify(data.error),
        };
      }

      return { success: true, result: data.result };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async runTaskInCloud(
    taskId: string,
    branch?: string | null,
    options?: CloudRunOptions & {
      resumeFromRunId?: string;
      pendingUserMessage?: string;
      pendingUserArtifactIds?: string[];
    },
  ): Promise<Task> {
    const teamId = await this.getTeamId();
    const body = buildCloudRunRequestBody({
      ...options,
      branch,
      mode: "interactive",
    });

    const data = await this.withCloudUsageLimitCheck(() =>
      this.api.post(`/api/projects/{project_id}/tasks/{id}/run/`, {
        path: { project_id: teamId.toString(), id: taskId },
        body,
      }),
    );

    return data as unknown as Task;
  }

  async warmTask(options: {
    repository: string;
    github_integration: number;
    branch?: string | null;
    runtime_adapter?: string | null;
    model?: string | null;
    reasoning_effort?: string | null;
    sandbox_environment_id?: string | null;
    custom_image_id?: string | null;
  }): Promise<{ task_id: string; run_id: string } | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/warm/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: {
        body: JSON.stringify({
          repository: options.repository,
          github_integration: options.github_integration,
          branch: options.branch ?? null,
          runtime_adapter: options.runtime_adapter ?? null,
          model: options.model ?? null,
          reasoning_effort: options.reasoning_effort ?? null,
          ...(options.sandbox_environment_id
            ? { sandbox_environment_id: options.sandbox_environment_id }
            : {}),
          ...(options.custom_image_id
            ? { custom_image_id: options.custom_image_id }
            : {}),
        }),
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to warm task: ${response.statusText}`);
    }
    const text = await response.text();
    if (!text) {
      return null;
    }
    return JSON.parse(text) as { task_id: string; run_id: string };
  }

  async prepareTaskStagedArtifactUploads(
    taskId: string,
    artifacts: TaskArtifactUploadRequest[],
  ): Promise<PreparedTaskArtifactUpload[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/staged_artifacts/prepare_upload/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/staged_artifacts/prepare_upload/`,
      overrides: {
        body: JSON.stringify({ artifacts }),
      },
    });

    if (!response.ok) {
      throw new Error(
        `Failed to prepare staged uploads: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      artifacts?: PreparedTaskArtifactUpload[];
    };
    return data.artifacts ?? [];
  }

  async finalizeTaskStagedArtifactUploads(
    taskId: string,
    artifacts: PreparedTaskArtifactUpload[],
  ): Promise<FinalizedTaskArtifactUpload[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/staged_artifacts/finalize_upload/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/staged_artifacts/finalize_upload/`,
      overrides: {
        body: JSON.stringify({
          artifacts: artifacts.map((artifact) => ({
            id: artifact.id,
            name: artifact.name,
            type: artifact.type,
            source: artifact.source,
            content_type: artifact.content_type,
            metadata: artifact.metadata,
            storage_path: artifact.storage_path,
          })),
        }),
      },
    });

    if (!response.ok) {
      throw new Error(
        `Failed to finalize staged uploads: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      artifacts?: FinalizedTaskArtifactUpload[];
    };
    return data.artifacts ?? [];
  }

  async prepareTaskRunArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: TaskArtifactUploadRequest[],
  ): Promise<PreparedTaskArtifactUpload[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/prepare_upload/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/prepare_upload/`,
      overrides: {
        body: JSON.stringify({ artifacts }),
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to prepare uploads: ${response.statusText}`);
    }

    const data = (await response.json()) as {
      artifacts?: PreparedTaskArtifactUpload[];
    };
    return data.artifacts ?? [];
  }

  async finalizeTaskRunArtifactUploads(
    taskId: string,
    runId: string,
    artifacts: PreparedTaskArtifactUpload[],
  ): Promise<FinalizedTaskArtifactUpload[]> {
    if (!artifacts.length) {
      return [];
    }

    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/finalize_upload/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/finalize_upload/`,
      overrides: {
        body: JSON.stringify({
          artifacts: artifacts.map((artifact) => ({
            id: artifact.id,
            name: artifact.name,
            type: artifact.type,
            source: artifact.source,
            content_type: artifact.content_type,
            metadata: artifact.metadata,
            storage_path: artifact.storage_path,
          })),
        }),
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to finalize uploads: ${response.statusText}`);
    }

    const data = (await response.json()) as {
      artifacts?: FinalizedTaskArtifactUpload[];
    };
    return data.artifacts ?? [];
  }

  async presignTaskRunArtifact(
    taskId: string,
    runId: string,
    storagePath: string,
  ): Promise<string> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/presign/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/presign/`,
      overrides: {
        body: JSON.stringify({ storage_path: storagePath }),
      },
    });

    if (!response.ok) {
      throw new Error(
        `Failed to generate artifact preview URL: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as { url: string };
    return data.url;
  }

  async resumeRunInCloud(taskId: string, runId: string): Promise<TaskRun> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/resume_in_cloud/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/resume_in_cloud/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to resume run in cloud: ${response.statusText}`);
    }

    return (await response.json()) as TaskRun;
  }

  async listTaskRuns(taskId: string): Promise<TaskRun[]> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch task runs: ${response.statusText}`);
    }

    const data = (await response.json()) as { results?: TaskRun[] };
    return data.results ?? [];
  }

  async getTaskRun(taskId: string, runId: string): Promise<TaskRun> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch task run: ${response.statusText}`);
    }

    return (await response.json()) as TaskRun;
  }

  async createTaskRun(
    taskId: string,
    options?: CreateTaskRunOptions,
  ): Promise<TaskRun> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/`,
    );
    const response = await this.withCloudUsageLimitCheck(() =>
      this.api.fetcher.fetch({
        method: "post",
        url,
        path: `/api/projects/${teamId}/tasks/${taskId}/runs/`,
        overrides: {
          body: JSON.stringify({
            ...buildCloudRunRequestBody({
              ...options,
              mode: options?.mode ?? "background",
            }),
            environment: options?.environment ?? "local",
          }),
        },
      }),
    );

    if (!response.ok) {
      throw new Error(`Failed to create task run: ${response.statusText}`);
    }

    return (await response.json()) as TaskRun;
  }

  async startTaskRun(
    taskId: string,
    runId: string,
    options?: StartTaskRunOptions,
  ): Promise<Task> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/start/`,
    );
    const response = await this.withCloudUsageLimitCheck(() =>
      this.api.fetcher.fetch({
        method: "post",
        url,
        path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/start/`,
        overrides: {
          body: JSON.stringify({
            pending_user_message: options?.pendingUserMessage,
            pending_user_artifact_ids: options?.pendingUserArtifactIds,
          }),
        },
      }),
    );

    if (!response.ok) {
      throw new Error(`Failed to start task run: ${response.statusText}`);
    }

    return (await response.json()) as Task;
  }

  async updateTaskRun(
    taskId: string,
    runId: string,
    updates: Partial<
      Pick<
        TaskRun,
        "status" | "branch" | "stage" | "error_message" | "output" | "state"
      >
    >,
  ): Promise<TaskRun> {
    const teamId = await this.getTeamId();
    const data = await this.api.patch(
      `/api/projects/{project_id}/tasks/{task_id}/runs/{id}/`,
      {
        path: {
          project_id: teamId.toString(),
          task_id: taskId,
          id: runId,
        },
        body: updates as Record<string, unknown>,
      },
    );
    return data as unknown as TaskRun;
  }

  /**
   * Append events to a task run's S3 log file
   */
  async appendTaskRunLog(
    taskId: string,
    runId: string,
    entries: StoredLogEntry[],
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const url = `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/append_log/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(url),
      path: url,
      overrides: {
        body: JSON.stringify({ entries }),
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to append log: ${response.statusText}`);
    }
  }

  async getTaskRunSessionLogs(
    taskId: string,
    runId: string,
    options?: { limit?: number; after?: string },
  ): Promise<StoredLogEntry[]> {
    return (await this.getTaskRunSessionLogsResult(taskId, runId, options))
      .entries;
  }

  async getTaskRunSessionLogsResult(
    taskId: string,
    runId: string,
    options?: { limit?: number; after?: string },
  ): Promise<TaskRunSessionLogsResult> {
    const maxEntries = options?.limit ?? SESSION_LOGS_MAX_PAGE_SIZE;
    const entries: StoredLogEntry[] = [];
    try {
      const teamId = await this.getTeamId();
      const path = `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/session_logs/`;
      let offset = 0;
      while (entries.length < maxEntries) {
        const url = new URL(`${this.api.baseUrl}${path}`);
        url.searchParams.set(
          "limit",
          String(
            Math.min(SESSION_LOGS_MAX_PAGE_SIZE, maxEntries - entries.length),
          ),
        );
        if (offset > 0) {
          url.searchParams.set("offset", String(offset));
        }
        if (options?.after) {
          url.searchParams.set("after", options.after);
        }
        const response = await this.api.fetcher.fetch({
          method: "get",
          url,
          path,
        });

        if (!response.ok) {
          log.warn(
            `Failed to fetch session logs page at offset ${offset}: ${response.status} ${response.statusText}`,
          );
          return { entries, complete: false };
        }

        const page = (await response.json()) as StoredLogEntry[];
        entries.push(...page);
        const hasMore = response.headers.get("X-Has-More") === "true";
        if (!hasMore || page.length === 0) {
          return { entries, complete: true };
        }
        offset += page.length;
      }
      return { entries, complete: false };
    } catch (err) {
      log.warn("Failed to fetch task run session logs", err);
      return { entries, complete: false };
    }
  }

  async getTaskLogs(taskId: string): Promise<StoredLogEntry[]> {
    try {
      const task = (await this.getTask(taskId)) as unknown as Task;
      const logUrl = task?.latest_run?.log_url;

      if (!logUrl) {
        return [];
      }

      const response = await fetch(logUrl);

      if (!response.ok) {
        log.warn(
          `Failed to fetch logs: ${response.status} ${response.statusText}`,
        );
        return [];
      }

      const content = await response.text();

      if (!content.trim()) {
        return [];
      }
      return content
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line) as StoredLogEntry);
    } catch (err) {
      log.warn("Failed to fetch task logs from latest run", err);
      return [];
    }
  }

  async getIntegrations() {
    const teamId = await this.getTeamId();
    return this.getIntegrationsForProject(teamId);
  }

  async getIntegrationsForProject(projectId: number) {
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${projectId}/integrations/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/environments/${projectId}/integrations/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch integrations: ${response.statusText}`);
    }

    const data = (await response.json()) as {
      results?: { kind: string; id: number | string; [key: string]: unknown }[];
    };
    return data.results ?? [];
  }

  async getGithubBranches(
    integrationId: string | number,
    repo: string,
  ): Promise<{ branches: string[]; defaultBranch: string | null }> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/integrations/${integrationId}/github_branches/`,
    );
    url.searchParams.set("repo", repo);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/environments/${teamId}/integrations/${integrationId}/github_branches/`,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch GitHub branches: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      branches?: string[];
      results?: string[];
      default_branch?: string | null;
    };
    return {
      branches: data.branches ?? data.results ?? [],
      defaultBranch: data.default_branch ?? null,
    };
  }

  async getGithubBranchesPage(
    integrationId: string | number,
    repo: string,
    offset: number,
    limit: number,
    search?: string,
  ): Promise<{
    branches: string[];
    defaultBranch: string | null;
    hasMore: boolean;
  }> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/integrations/${integrationId}/github_branches/`,
    );
    url.searchParams.set("repo", repo);
    url.searchParams.set("offset", String(offset));
    url.searchParams.set("limit", String(limit));
    if (search?.trim()) {
      url.searchParams.set("search", search.trim());
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/environments/${teamId}/integrations/${integrationId}/github_branches/`,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch GitHub branches: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      branches?: string[];
      results?: string[];
      default_branch?: string | null;
      has_more?: boolean;
    };
    return {
      branches: data.branches ?? data.results ?? [],
      defaultBranch: data.default_branch ?? null,
      hasMore: data.has_more ?? false,
    };
  }

  async getGithubUserBranchesPage(
    installationId: string | number,
    repo: string,
    offset: number,
    limit: number,
    search?: string,
  ): Promise<{
    branches: string[];
    defaultBranch: string | null;
    hasMore: boolean;
  }> {
    const urlPath = `/api/users/@me/integrations/github/${installationId}/branches/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    url.searchParams.set("repo", repo);
    url.searchParams.set("offset", String(offset));
    url.searchParams.set("limit", String(limit));
    if (search?.trim()) {
      url.searchParams.set("search", search.trim());
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch personal GitHub branches: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      branches?: string[];
      results?: string[];
      default_branch?: string | null;
      has_more?: boolean;
    };
    return {
      branches: data.branches ?? data.results ?? [],
      defaultBranch: data.default_branch ?? null,
      hasMore: data.has_more ?? false,
    };
  }

  async getGithubRepositories(
    integrationId: string | number,
  ): Promise<string[]> {
    const repositories: string[] = [];
    let offset = 0;

    while (true) {
      const page = await this.getGithubRepositoriesPage(
        integrationId,
        offset,
        500,
      );
      repositories.push(...page.repositories);

      if (!page.hasMore) {
        return repositories;
      }

      offset += page.repositories.length;
    }
  }

  async getGithubRepositoriesPage(
    integrationId: string | number,
    offset: number,
    limit: number,
    search?: string,
  ): Promise<{
    repositories: string[];
    hasMore: boolean;
  }> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/integrations/${integrationId}/github_repos/`,
    );
    url.searchParams.set("offset", String(offset));
    url.searchParams.set("limit", String(limit));
    if (search?.trim()) {
      url.searchParams.set("search", search.trim());
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/environments/${teamId}/integrations/${integrationId}/github_repos/`,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch GitHub repositories: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as { has_more?: boolean };
    return {
      repositories: this.normalizeGithubRepositories(data),
      hasMore: data.has_more ?? false,
    };
  }

  async getGithubUserRepositories(
    installationId: string | number,
  ): Promise<string[]> {
    const repositories: string[] = [];
    let offset = 0;

    while (true) {
      const page = await this.getGithubUserRepositoriesPage(
        installationId,
        offset,
        500,
      );
      repositories.push(...page.repositories);

      if (!page.hasMore) {
        return repositories;
      }

      offset += page.repositories.length;
    }
  }

  async getGithubUserRepositoriesPage(
    installationId: string | number,
    offset: number,
    limit: number,
    search?: string,
  ): Promise<{
    repositories: string[];
    hasMore: boolean;
  }> {
    const urlPath = `/api/users/@me/integrations/github/${installationId}/repos/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    url.searchParams.set("offset", String(offset));
    url.searchParams.set("limit", String(limit));
    if (search?.trim()) {
      url.searchParams.set("search", search.trim());
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch personal GitHub repositories: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as { has_more?: boolean };
    return {
      repositories: this.normalizeGithubRepositories(data),
      hasMore: data.has_more ?? false,
    };
  }

  async refreshGithubRepositories(
    integrationId: string | number,
  ): Promise<string[]> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/integrations/${integrationId}/github_repos/refresh/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/environments/${teamId}/integrations/${integrationId}/github_repos/refresh/`,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to refresh GitHub repositories: ${response.statusText}`,
      );
    }

    const data: unknown = await response.json();
    return this.normalizeGithubRepositories(data);
  }

  async refreshGithubUserRepositories(
    installationId: string | number,
  ): Promise<string[]> {
    const urlPath = `/api/users/@me/integrations/github/${installationId}/repos/refresh/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to refresh personal GitHub repositories: ${response.statusText}`,
      );
    }

    const data: unknown = await response.json();
    return this.normalizeGithubRepositories(data);
  }

  private normalizeGithubRepositories(data: unknown): string[] {
    const repos =
      (data as { repositories?: unknown[] }).repositories ??
      (data as { results?: unknown[] }).results ??
      (Array.isArray(data) ? data : []);

    return (repos as (string | { full_name?: string; name?: string })[]).map(
      (repo) => {
        if (typeof repo === "string") return repo;
        return (repo.full_name ?? repo.name ?? "").toLowerCase();
      },
    );
  }

  async getAgents() {
    const teamId = await this.getTeamId();
    const url = new URL(`${this.api.baseUrl}/api/projects/${teamId}/agents/`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/agents/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch agents: ${response.statusText}`);
    }

    const data = (await response.json()) as { results?: unknown[] };
    return data.results ?? [];
  }

  async getUsers() {
    const data = (await this.api.get("/api/users/", {
      query: { limit: 1000 },
    })) as unknown as { results: Schemas.User[] } | Schemas.User[];
    return Array.isArray(data) ? data : (data.results ?? []);
  }

  async updateTeam(updates: {
    session_recording_opt_in?: boolean;
    autocapture_exceptions_opt_in?: boolean;
  }): Promise<Schemas.Team> {
    const teamId = await this.getTeamId();
    const url = new URL(`${this.api.baseUrl}/api/projects/${teamId}/`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: `/api/projects/${teamId}/`,
      overrides: {
        body: JSON.stringify(updates),
      },
    });

    if (!response.ok) {
      const responseText = await response.text();
      let detail = responseText;
      try {
        const parsed = JSON.parse(responseText) as
          | { detail?: string }
          | Record<string, unknown>;
        if (
          typeof parsed === "object" &&
          parsed !== null &&
          "detail" in parsed &&
          typeof parsed.detail === "string"
        ) {
          detail = parsed.detail;
        } else if (typeof parsed === "object" && parsed !== null) {
          detail = Object.entries(parsed)
            .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
            .join(", ");
        }
      } catch {
        // keep plain text fallback
      }

      throw new Error(
        `Failed to update team: ${detail || response.statusText}`,
      );
    }

    return (await response.json()) as Schemas.Team;
  }

  async getSignalReport(reportId: string): Promise<SignalReport | null> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);

    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path,
      });
      return (await response.json()) as SignalReport;
    } catch (error) {
      // The shared fetcher throws "Failed request: [<status>] <body>" for any
      // non-2xx. Treat missing / forbidden as "not available in the current
      // team" and surface other errors to the caller.
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("[404]") || msg.includes("[403]")) {
        return null;
      }
      throw error;
    }
  }

  async getSignalReports(
    params?: SignalReportsQueryParams,
  ): Promise<SignalReportsResponse> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/`,
    );

    if (params?.limit != null) {
      url.searchParams.set("limit", String(params.limit));
    }
    if (params?.offset != null) {
      url.searchParams.set("offset", String(params.offset));
    }
    if (params?.status) {
      url.searchParams.set("status", params.status);
    }
    if (params?.ordering) {
      url.searchParams.set("ordering", params.ordering);
    }
    if (params?.source_product) {
      url.searchParams.set("source_product", params.source_product);
    }
    if (params?.suggested_reviewers) {
      url.searchParams.set("suggested_reviewers", params.suggested_reviewers);
    }
    if (params?.priority) {
      url.searchParams.set("priority", params.priority);
    }
    if (params?.has_implementation_pr != null) {
      url.searchParams.set(
        "has_implementation_pr",
        String(params.has_implementation_pr),
      );
    }

    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/signals/reports/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch signal reports: ${response.statusText}`);
    }

    const data = (await response.json()) as {
      results?: SignalReport[];
      count?: number;
    };
    return {
      results: data.results ?? [],
      count: data.count ?? data.results?.length ?? 0,
    };
  }

  async getSignalProcessingState(): Promise<SignalProcessingStateResponse> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/processing/`,
    );
    const path = `/api/projects/${teamId}/signals/processing/`;

    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch signal processing state: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as { paused_until?: string | null };
    return {
      paused_until:
        typeof data?.paused_until === "string" ? data.paused_until : null,
    };
  }

  async getAvailableSuggestedReviewers(
    query?: string,
  ): Promise<AvailableSuggestedReviewersResponse> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/available_reviewers/`,
    );
    const path = `/api/projects/${teamId}/signals/reports/available_reviewers/`;

    if (query?.trim()) {
      url.searchParams.set("query", query.trim());
    }

    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch available suggested reviewers: ${response.statusText}`,
      );
    }

    return parseAvailableSuggestedReviewersPayload(await response.json());
  }

  async getSignalReportSignals(
    reportId: string,
  ): Promise<SignalReportSignalsResponse> {
    try {
      const teamId = await this.getTeamId();
      const url = new URL(
        `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/${reportId}/signals/`,
      );
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: `/api/projects/${teamId}/signals/reports/${reportId}/signals/`,
      });

      if (!response.ok) {
        log.warn("Signal report signals unavailable", {
          reportId,
          status: response.status,
        });
        return { report: null, signals: [] };
      }

      const data = (await response.json()) as {
        report?: SignalReport | null;
        signals?: Signal[];
      };
      return {
        report: data.report ?? null,
        signals: data.signals ?? [],
      };
    } catch (error) {
      log.warn("Failed to fetch signal report signals", { reportId, error });
      return { report: null, signals: [] };
    }
  }

  async getSignalReportArtefacts(
    reportId: string,
  ): Promise<SignalReportArtefactsResponse> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/${reportId}/artefacts/`,
    );
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/artefacts/`;

    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path,
      });

      if (!response.ok) {
        const responseText = await response.text();
        const unavailableReason =
          response.status === 403
            ? "forbidden"
            : response.status === 404
              ? "not_found"
              : "request_failed";

        log.warn("Signal report artefacts unavailable", {
          teamId,
          reportId,
          status: response.status,
          statusText: response.statusText,
          body: responseText || undefined,
        });

        return { results: [], count: 0, unavailableReason };
      }

      const data = (await response.json()) as unknown;
      const parsed = parseSignalReportArtefactsPayload(data);

      if (parsed.unavailableReason) {
        log.warn("Signal report artefacts payload did not match schema", {
          teamId,
          reportId,
        });
      }

      return parsed;
    } catch (error) {
      log.warn("Failed to fetch signal report artefacts", {
        teamId,
        reportId,
        error,
      });
      return {
        results: [],
        count: 0,
        unavailableReason: "request_failed",
      };
    }
  }

  async getCommitDiff(
    reportId: string,
    artefactId: string,
  ): Promise<CommitDiffResponse> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/artefacts/${artefactId}/diff/`;
    const url = new URL(`${this.api.baseUrl}${path}`);

    // The shared fetcher throws `Failed request: [<status>] <json-body>` for any non-2xx, so
    // unwrap that into the endpoint's clean `error` message rather than surfacing the raw string.
    let response: Response;
    try {
      response = await this.api.fetcher.fetch({ method: "get", url, path });
    } catch (error) {
      throw new Error(
        extractRequestErrorMessage(error, "Couldn\u2019t load the diff."),
      );
    }

    const data = (await response.json()) as Partial<CommitDiffResponse>;
    return {
      diff: typeof data.diff === "string" ? data.diff : "",
      truncated: data.truncated === true,
    };
  }

  async updateSignalReportState(
    reportId: string,
    input:
      | {
          state: "potential";
          snooze_for?: number;
          reset_weight?: boolean;
          error?: string;
        }
      | {
          state: "suppressed";
          /** When omitted, the server suppresses without creating a dismissal artefact. */
          dismissal_reason?: DismissalReasonOptionValue;
          dismissal_note?: string;
          reset_weight?: boolean;
          error?: string;
        },
  ): Promise<SignalReport> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/${reportId}/state/`,
    );
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/state/`;

    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify(input),
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to update signal report state");
    }

    return (await response.json()) as SignalReport;
  }

  /**
   * Edit a report's suggested reviewers. The server appends a new `suggested_reviewers` status
   * artefact (latest-wins), canonicalizes each entry to a lowercase `github_login`, and carries
   * `relevant_commits` / `github_name` forward from the current reviewers for surviving logins.
   * Returns the newly-appended artefact (a fresh id), not the one addressed by `artefactId`.
   */
  async updateSignalReportArtefact(
    reportId: string,
    artefactId: string,
    content: SuggestedReviewerWriteEntry[],
  ): Promise<SuggestedReviewersArtefact> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/${reportId}/artefacts/${artefactId}/`,
    );
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/artefacts/${artefactId}/`;

    const response = await this.api.fetcher.fetch({
      method: "put",
      url,
      path,
      overrides: {
        body: JSON.stringify({ content }),
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to update suggested reviewers");
    }

    const parsed = normalizeSignalReportArtefact(await response.json());
    if (!parsed || parsed.type !== "suggested_reviewers") {
      throw new Error("Unexpected response updating suggested reviewers");
    }
    return parsed as SuggestedReviewersArtefact;
  }

  async deleteSignalReport(reportId: string): Promise<{
    status: "deletion_started" | "already_running";
    report_id: string;
  }> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/${reportId}/`,
    );
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/`;

    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to delete signal report");
    }

    return (await response.json()) as {
      status: "deletion_started" | "already_running";
      report_id: string;
    };
  }

  async reingestSignalReport(reportId: string): Promise<{
    status: "reingestion_started" | "already_running";
    report_id: string;
  }> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/reports/${reportId}/reingest/`,
    );
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/reingest/`;

    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Failed to reingest signal report");
    }

    return (await response.json()) as {
      status: "reingestion_started" | "already_running";
      report_id: string;
    };
  }

  async getSignalTeamConfig(): Promise<SignalTeamConfig> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/config/`,
    );
    const path = `/api/projects/${teamId}/signals/config/`;

    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch signal team config: ${response.statusText}`,
      );
    }

    return (await response.json()) as SignalTeamConfig;
  }

  async updateSignalTeamConfig(
    updates: Partial<{
      default_autostart_priority: string;
      default_slack_notification_channel: string | null;
      autostart_base_branches: Record<string, string>;
    }>,
  ): Promise<SignalTeamConfig> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/signals/config/`,
    );
    const path = `/api/projects/${teamId}/signals/config/`;

    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify(updates),
      },
    });

    if (!response.ok) {
      throw new Error(
        `Failed to update signal team config: ${response.statusText}`,
      );
    }

    return (await response.json()) as SignalTeamConfig;
  }

  async getSignalUserAutonomyConfig(): Promise<SignalUserAutonomyConfig | null> {
    const url = new URL(`${this.api.baseUrl}/api/users/@me/signal_autonomy/`);
    const path = "/api/users/@me/signal_autonomy/";

    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    return (await response.json()) as SignalUserAutonomyConfig;
  }

  async updateSignalUserAutonomyConfig(
    updates: Partial<{
      autostart_priority: string | null;
      slack_notification_integration_id: number | null;
      slack_notification_channel: string | null;
      slack_notification_min_priority: string | null;
    }>,
  ): Promise<SignalUserAutonomyConfig> {
    const url = new URL(`${this.api.baseUrl}/api/users/@me/signal_autonomy/`);
    const path = "/api/users/@me/signal_autonomy/";

    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify(updates),
      },
    });

    if (!response.ok) {
      throw new Error(
        `Failed to update signal user autonomy config: ${response.statusText}`,
      );
    }
    return (await response.json()) as SignalUserAutonomyConfig;
  }

  async getSlackChannelsForIntegration(
    integrationId: number,
    params?: SlackChannelsQueryParams,
  ): Promise<SlackChannelsResponse> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/integrations/${integrationId}/channels/`,
    );
    const search = params?.search?.trim();
    if (search) {
      url.searchParams.set("search", search);
    }
    if (params?.limit != null) {
      url.searchParams.set("limit", String(params.limit));
    }
    if (params?.offset != null) {
      url.searchParams.set("offset", String(params.offset));
    }
    if (params?.channelId) {
      url.searchParams.set("channel_id", params.channelId);
    }
    const path = `/api/environments/${teamId}/integrations/${integrationId}/channels/${url.search}`;

    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch Slack channels: ${response.statusText}`);
    }
    return (await response.json()) as SlackChannelsResponse;
  }

  async deleteSignalUserAutonomyConfig(): Promise<void> {
    const url = new URL(`${this.api.baseUrl}/api/users/@me/signal_autonomy/`);
    const path = "/api/users/@me/signal_autonomy/";

    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to delete signal user autonomy config: ${response.statusText}`,
      );
    }
  }

  async getMcpServers(): Promise<McpRecommendedServer[]> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/mcp_servers/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/environments/${teamId}/mcp_servers/`,
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch MCP servers: ${response.statusText}`);
    }

    const data = (await response.json()) as {
      results?: McpRecommendedServer[];
    };
    return data.results ?? [];
  }

  /**
   * Object URL for an MCP server's brand icon, proxied from logo.dev by the
   * authenticated `mcp_servers/icon/` endpoint. Returns null when no brand
   * icon exists for the domain (the endpoint 404s so callers render their own
   * fallback glyph, e.g. on self-hosted instances without a logo.dev token).
   */
  async getMcpServerIconUrl(
    domain: string,
    theme?: "light" | "dark",
  ): Promise<string | null> {
    const teamId = await this.getTeamId();
    const path = `/api/environments/${teamId}/mcp_servers/icon/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("domain", domain);
    if (theme) {
      url.searchParams.set("theme", theme);
    }
    let response: Response;
    try {
      response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path,
      });
    } catch (error) {
      // 404 is the endpoint's definitive "no icon for this domain" answer,
      // not a failure; anything else propagates so callers can retry.
      if (requestErrorStatus(error) === 404) return null;
      throw error;
    }
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  }

  async getMcpServerInstallations(): Promise<McpServerInstallation[]> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/mcp_server_installations/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/environments/${teamId}/mcp_server_installations/`,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch MCP server installations: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      results?: McpServerInstallation[];
    };
    return data.results ?? [];
  }

  async installCustomMcpServer(options: {
    name: string;
    url: string;
    auth_type: McpAuthType;
    api_key?: string;
    description?: string;
    client_id?: string;
    client_secret?: string;
    install_source?: "posthog" | "posthog-code";
    posthog_code_callback_url?: string;
  }): Promise<McpServerInstallation | Schemas.OAuthRedirectResponse> {
    const teamId = await this.getTeamId();
    const apiUrl = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/mcp_server_installations/install_custom/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: apiUrl,
      path: `/api/environments/${teamId}/mcp_server_installations/install_custom/`,
      overrides: {
        body: JSON.stringify(options),
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `Failed to install MCP server: ${response.statusText}`,
      );
    }

    return (await response.json()) as
      | McpServerInstallation
      | Schemas.OAuthRedirectResponse;
  }

  async updateMcpServerInstallation(
    installationId: string,
    updates: {
      display_name?: string;
      description?: string;
      is_enabled?: boolean;
    },
  ): Promise<McpServerInstallation> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/mcp_server_installations/${installationId}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: `/api/environments/${teamId}/mcp_server_installations/${installationId}/`,
      overrides: {
        body: JSON.stringify(updates),
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `Failed to update MCP server: ${response.statusText}`,
      );
    }

    return (await response.json()) as McpServerInstallation;
  }

  async uninstallMcpServer(installationId: string): Promise<void> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/environments/${teamId}/mcp_server_installations/${installationId}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: `/api/environments/${teamId}/mcp_server_installations/${installationId}/`,
    });

    if (!response.ok && response.status !== 204) {
      throw new Error(`Failed to uninstall MCP server: ${response.statusText}`);
    }
  }

  async installMcpTemplate(options: {
    template_id: string;
    api_key?: string;
    install_source?: "posthog" | "posthog-code";
    posthog_code_callback_url?: string;
  }): Promise<McpServerInstallation | Schemas.OAuthRedirectResponse> {
    const teamId = await this.getTeamId();
    const path = `/api/environments/${teamId}/mcp_server_installations/install_template/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${path}`),
      path,
      overrides: { body: JSON.stringify(options) },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `Failed to install MCP template: ${response.statusText}`,
      );
    }

    return (await response.json()) as
      | McpServerInstallation
      | Schemas.OAuthRedirectResponse;
  }

  async authorizeMcpInstallation(options: {
    installation_id: string;
    install_source?: "posthog" | "posthog-code";
    posthog_code_callback_url?: string;
  }): Promise<Schemas.OAuthRedirectResponse> {
    const teamId = await this.getTeamId();
    const path = `/api/environments/${teamId}/mcp_server_installations/authorize/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("installation_id", options.installation_id);
    if (options.install_source) {
      url.searchParams.set("install_source", options.install_source);
    }
    if (options.posthog_code_callback_url) {
      url.searchParams.set(
        "posthog_code_callback_url",
        options.posthog_code_callback_url,
      );
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `Failed to authorize MCP installation: ${response.statusText}`,
      );
    }

    return (await response.json()) as Schemas.OAuthRedirectResponse;
  }

  async getMcpInstallationTools(
    installationId: string,
    options: { includeRemoved?: boolean } = {},
  ): Promise<McpInstallationTool[]> {
    const teamId = await this.getTeamId();
    const path = `/api/environments/${teamId}/mcp_server_installations/${installationId}/tools/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (options.includeRemoved) {
      url.searchParams.set("include_removed", "1");
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to fetch MCP installation tools: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      results?: McpInstallationTool[];
    };
    return data.results ?? [];
  }

  async updateMcpToolApproval(
    installationId: string,
    toolName: string,
    approval_state: McpApprovalState,
  ): Promise<McpInstallationTool> {
    const teamId = await this.getTeamId();
    const path = `/api/environments/${teamId}/mcp_server_installations/${installationId}/tools/${encodeURIComponent(toolName)}/`;
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url: new URL(`${this.api.baseUrl}${path}`),
      path,
      overrides: { body: JSON.stringify({ approval_state }) },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `Failed to update tool approval: ${response.statusText}`,
      );
    }

    return (await response.json()) as McpInstallationTool;
  }

  async refreshMcpInstallationTools(
    installationId: string,
  ): Promise<McpInstallationTool[]> {
    const teamId = await this.getTeamId();
    const path = `/api/environments/${teamId}/mcp_server_installations/${installationId}/tools/refresh/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${path}`),
      path,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `Failed to refresh MCP tools: ${response.statusText}`,
      );
    }

    const data = (await response.json()) as {
      results?: McpInstallationTool[];
    };
    return data.results ?? [];
  }

  private parseFetcherError(error: unknown): {
    status: number;
    body: Record<string, unknown>;
  } | null {
    if (!(error instanceof Error)) return null;
    const match = error.message.match(/\[(\d+)\]\s*(.*)/);
    if (!match) return null;
    try {
      return {
        status: Number.parseInt(match[1], 10),
        body: JSON.parse(match[2]) as Record<string, unknown>,
      };
    } catch {
      return { status: Number.parseInt(match[1], 10), body: {} };
    }
  }

  /**
   * Run a cloud-run request, re-throwing a backend 429 usage-limit error as a
   * typed CloudUsageLimitError so the UI can show the upgrade prompt.
   */
  private async withCloudUsageLimitCheck<T>(fn: () => Promise<T>): Promise<T> {
    try {
      return await fn();
    } catch (error) {
      const parsed = this.parseFetcherError(error);
      if (
        parsed &&
        parsed.status === 429 &&
        parsed.body.code === "usage_limit_exceeded"
      ) {
        const limitType = parsed.body.limit_type;
        throw new CloudUsageLimitError({
          limitType:
            limitType === "burst" || limitType === "sustained"
              ? limitType
              : null,
          resetAt:
            typeof parsed.body.reset_at === "string"
              ? parsed.body.reset_at
              : null,
          isPro: parsed.body.is_pro === true,
        });
      }
      throw error;
    }
  }

  /**
   * Check if a feature flag is enabled for the current project.
   * Returns true if the flag exists and is active, false otherwise.
   */
  async isFeatureFlagEnabled(flagKey: string): Promise<boolean> {
    try {
      const teamId = await this.getTeamId();
      const url = new URL(
        `${this.api.baseUrl}/api/projects/${teamId}/feature_flags/`,
      );
      url.searchParams.set("key", flagKey);

      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: `/api/projects/${teamId}/feature_flags/`,
      });

      if (!response.ok) {
        log.warn(`Failed to fetch feature flags: ${response.statusText}`);
        return false;
      }

      const data = (await response.json()) as {
        results?: { key: string; active: boolean }[];
      };
      const flags = data.results ?? [];
      const flag = flags.find(
        (f: { key: string; active: boolean }) => f.key === flagKey,
      );

      return flag?.active ?? false;
    } catch (error) {
      log.warn(`Error checking feature flag "${flagKey}":`, error);
      return false;
    }
  }

  // Sandbox Environments

  async listSandboxEnvironments(): Promise<SandboxEnvironment[]> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_environments/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/sandbox_environments/`,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch sandbox environments: ${response.statusText}`,
      );
    }
    const data = (await response.json()) as {
      results?: SandboxEnvironment[];
    };
    return data.results ?? [];
  }

  async createSandboxEnvironment(
    input: SandboxEnvironmentInput,
  ): Promise<SandboxEnvironment> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_environments/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/sandbox_environments/`,
      overrides: {
        body: JSON.stringify(input),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to create sandbox environment: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxEnvironment;
  }

  async updateSandboxEnvironment(
    id: string,
    input: Partial<SandboxEnvironmentInput>,
  ): Promise<SandboxEnvironment> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_environments/${id}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: `/api/projects/${teamId}/sandbox_environments/${id}/`,
      overrides: {
        body: JSON.stringify(input),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to update sandbox environment: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxEnvironment;
  }

  async deleteSandboxEnvironment(id: string): Promise<void> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_environments/${id}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: `/api/projects/${teamId}/sandbox_environments/${id}/`,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to delete sandbox environment: ${response.statusText}`,
      );
    }
  }

  async listSandboxCustomImages(): Promise<SandboxCustomImage[]> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/`,
    });
    if (!response.ok) {
      if (response.status === 403) {
        const errorData = (await response.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new SandboxCustomImagesDisabledError(errorData.detail);
      }
      throw new Error(
        `Failed to fetch sandbox custom images: ${response.statusText}`,
      );
    }
    const data = (await response.json()) as {
      results?: SandboxCustomImage[];
    };
    return data.results ?? [];
  }

  async createSandboxCustomImage(input: {
    name: string;
    description?: string;
    repository?: string | null;
    private?: boolean;
  }): Promise<SandboxCustomImage> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/`,
      overrides: {
        body: JSON.stringify(input),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to create sandbox custom image: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxCustomImage;
  }

  async getSandboxCustomImage(id: string): Promise<SandboxCustomImage> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/${id}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/${id}/`,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch sandbox custom image: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxCustomImage;
  }

  async updateSandboxCustomImage(
    id: string,
    input: { name?: string; description?: string },
  ): Promise<SandboxCustomImage> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/${id}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/${id}/`,
      overrides: {
        body: JSON.stringify(input),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to update sandbox custom image: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxCustomImage;
  }

  async ensureSandboxCustomImageBuilderTask(
    id: string,
  ): Promise<SandboxCustomImage> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/${id}/builder_task/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/${id}/builder_task/`,
      overrides: {
        body: JSON.stringify({}),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to open image builder session: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxCustomImage;
  }

  async buildSandboxCustomImage(
    id: string,
    specYaml?: string | null,
  ): Promise<SandboxCustomImage> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/${id}/build/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/${id}/build/`,
      overrides: {
        body: JSON.stringify(
          specYaml === undefined ? {} : { spec_yaml: specYaml },
        ),
      },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to build sandbox custom image: ${response.statusText}`,
      );
    }
    return (await response.json()) as SandboxCustomImage;
  }

  async deleteSandboxCustomImage(id: string): Promise<void> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_custom_images/${id}/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: `/api/projects/${teamId}/sandbox_custom_images/${id}/`,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to delete sandbox custom image: ${response.statusText}`,
      );
    }
  }

  /** Find an exported asset by session recording ID. */
  async findExportBySessionRecordingId(
    projectId: number,
    sessionRecordingId: string,
  ): Promise<number | null> {
    const urlPath = `/api/projects/${projectId}/exports/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    url.searchParams.set("session_recording_id", sessionRecordingId);
    url.searchParams.set("export_format", "video/mp4");
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) return null;
    const data = (await response.json()) as {
      results?: Array<{ id: number; has_content: boolean }>;
    };
    const match = data.results?.find((e) => e.has_content);
    return match?.id ?? null;
  }

  /** Get the presigned content URL for an exported asset (e.g. rasterized recording). */
  async getExportContentUrl(
    projectId: number,
    exportId: number,
  ): Promise<string | null> {
    const urlPath = `/api/projects/${projectId}/exports/${exportId}/content/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) return null;
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  }

  /**
   * Fetch the requesting user's personal LLM spend analysis. `dateFrom` / `dateTo`
   * accept absolute dates (`2026-04-23`) or relative strings (`-7d`, `-1m`), and
   * default to the last 30 days. When `product` is set the tool / model / trace
   * breakdowns are scoped to that `ai_product` (e.g. `posthog_code`); when omitted
   * they aggregate across every product.
   */
  async getPersonalSpendAnalysis(
    options: { dateFrom?: string; dateTo?: string; product?: string } = {},
  ): Promise<SpendAnalysisResponse> {
    const { dateFrom = "-30d", dateTo, product } = options;
    const urlPath = `/api/llm_analytics/@me/spend/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    url.searchParams.set("date_from", dateFrom);
    if (dateTo) {
      url.searchParams.set("date_to", dateTo);
    }
    if (product) {
      url.searchParams.set("product", product);
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch spend analysis: ${response.status}`);
    }
    return (await response.json()) as SpendAnalysisResponse;
  }

  /**
   * Lists the team's LLM skills (latest versions, no bodies).
   * Returns null when the feature is unavailable for this org (the
   * llm-analytics-skills flag gates the endpoint server-side with a 403).
   * `category` narrows to one exact server-owned category (e.g. "scout"
   * for Signals scouts); omit it to list every category.
   */
  async listLlmSkills(
    options: { category?: string } = {},
  ): Promise<LlmSkillListItem[] | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/environments/${teamId}/llm_skills/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    if (options.category !== undefined) {
      url.searchParams.set("category", options.category);
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (response.status === 403) return null;
    if (!response.ok) {
      throw new Error(`Failed to fetch team skills: ${response.statusText}`);
    }
    const data = (await response.json()) as { results?: LlmSkillListItem[] };
    return data.results ?? [];
  }

  /** Fetches the latest version of a team skill, including body and file manifest. */
  async getLlmSkillByName(name: string): Promise<LlmSkill> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/environments/${teamId}/llm_skills/name/${encodeURIComponent(name)}`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch team skill: ${response.statusText}`);
    }
    return (await response.json()) as LlmSkill;
  }

  /** Creates a brand-new team skill (version 1). */
  async createLlmSkill(input: {
    name: string;
    description: string;
    body: string;
    files?: LlmSkillFileInput[];
  }): Promise<LlmSkill> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/environments/${teamId}/llm_skills/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: { body: JSON.stringify(input) },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to create team skill: ${response.statusText}`,
      );
    }
    return (await response.json()) as LlmSkill;
  }

  /**
   * Publishes a new version of an existing team skill. `base_version` must
   * match the current latest version (409 otherwise).
   */
  async publishLlmSkillVersion(
    name: string,
    input: {
      body: string;
      description?: string;
      files?: LlmSkillFileInput[];
      base_version: number;
    },
  ): Promise<LlmSkill> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/environments/${teamId}/llm_skills/name/${encodeURIComponent(name)}`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path: urlPath,
      overrides: { body: JSON.stringify(input) },
    });
    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as {
        detail?: string;
      };
      throw new Error(
        errorData.detail ??
          `Failed to publish team skill: ${response.statusText}`,
      );
    }
    return (await response.json()) as LlmSkill;
  }

  /** Fetches one companion file of a team skill. */
  async getLlmSkillFile(name: string, filePath: string): Promise<LlmSkillFile> {
    const teamId = await this.getTeamId();
    const encodedPath = filePath.split("/").map(encodeURIComponent).join("/");
    const urlPath = `/api/environments/${teamId}/llm_skills/name/${encodeURIComponent(name)}/files/${encodedPath}`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch team skill file: ${response.statusText}`,
      );
    }
    return (await response.json()) as LlmSkillFile;
  }

  // --- Agent platform ------------------------------------------------------
  // Deployed agents (`agent_platform` Django app). These routes aren't in the
  // generated OpenAPI client, so they use the raw fetcher. Applications are
  // addressable by UUID or slug in the `{idOrSlug}` segment.

  private agentApplicationsPath(teamId: number): string {
    return `/api/projects/${teamId}/agent_applications/`;
  }

  /** Lists non-archived agent applications for the current team. */
  async listAgentApplications(): Promise<AgentApplication[]> {
    const MAX_PAGES = 50;
    const teamId = await this.getTeamId();
    const all: AgentApplication[] = [];
    let urlPath = `${this.agentApplicationsPath(teamId)}?limit=100`;
    for (let i = 0; i < MAX_PAGES; i++) {
      const url = new URL(`${this.api.baseUrl}${urlPath}`);
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: urlPath,
      });
      const page = (await response.json()) as {
        results?: AgentApplication[];
        next?: string | null;
      };
      all.push(...(page.results ?? []));
      if (!page.next) return all;
      const nextUrl = new URL(page.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    return all;
  }

  /** Fetches a single agent application by UUID or slug; null if not found. */
  async getAgentApplication(
    idOrSlug: string,
  ): Promise<AgentApplication | null> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path,
      });
      return (await response.json()) as AgentApplication;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("[404]") || msg.includes("[403]")) {
        return null;
      }
      throw error;
    }
  }

  /** Lists sessions for an application (paginated, filterable by state). */
  async listAgentApplicationSessions(
    idOrSlug: string,
    params?: AgentSessionsListParams,
  ): Promise<AgentApplicationSessionsListResponse> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/sessions/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (params?.limit != null) {
      url.searchParams.set("limit", String(params.limit));
    }
    if (params?.offset != null) {
      url.searchParams.set("offset", String(params.offset));
    }
    if (params?.state?.length) {
      url.searchParams.set("state", params.state.join(","));
    }
    if (params?.revision_id) {
      url.searchParams.set("revision_id", params.revision_id);
    }
    if (params?.agent_user_id) {
      url.searchParams.set("agent_user_id", params.agent_user_id);
    }
    if (params?.created_after) {
      url.searchParams.set("created_after", params.created_after);
    }
    if (params?.created_before) {
      url.searchParams.set("created_before", params.created_before);
    }
    if (params?.search?.trim()) {
      url.searchParams.set("search", params.search.trim());
    }
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      results?: AgentApplicationSessionsListResponse["results"];
      count?: number;
    };
    return {
      results: data.results ?? [],
      count: data.count ?? data.results?.length ?? 0,
    };
  }

  /** Full session detail incl. transcript; `lastN` trims to trailing messages. */
  async getAgentApplicationSession(
    idOrSlug: string,
    sessionId: string,
    lastN?: number,
  ): Promise<AgentApplicationSessionDetail | null> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/sessions/${encodeURIComponent(sessionId)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (lastN != null) {
      url.searchParams.set("last_n", String(lastN));
    }
    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path,
      });
      return (await response.json()) as AgentApplicationSessionDetail;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("[404]") || msg.includes("[403]")) {
        return null;
      }
      throw error;
    }
  }

  /** Structured runtime logs for one session (ClickHouse log_entries). */
  async getAgentApplicationSessionLogs(
    idOrSlug: string,
    sessionId: string,
    params?: AgentSessionLogsParams,
  ): Promise<AgentSessionLogEntry[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/sessions/${encodeURIComponent(sessionId)}/logs/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (params?.limit != null) {
      url.searchParams.set("limit", String(params.limit));
    }
    if (params?.level?.length) {
      url.searchParams.set("level", params.level.join(","));
    }
    if (params?.search) {
      url.searchParams.set("search", params.search);
    }
    if (params?.after) {
      url.searchParams.set("after", params.after);
    }
    if (params?.before) {
      url.searchParams.set("before", params.before);
    }
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      results?: AgentSessionLogEntry[];
    };
    return data.results ?? [];
  }

  /** Lists tool-approval requests for an application (team-admin only). */
  async listAgentApplicationApprovals(
    idOrSlug: string,
    params?: AgentApprovalsListParams,
  ): Promise<AgentApprovalRequest[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/approvals/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (params?.state) {
      url.searchParams.set("state", params.state);
    }
    if (params?.limit != null) {
      url.searchParams.set("limit", String(params.limit));
    }
    if (params?.offset != null) {
      url.searchParams.set("offset", String(params.offset));
    }
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      results?: AgentApprovalRequest[];
    };
    return data.results ?? [];
  }

  /** Approve or reject a queued tool-approval request. */
  async decideAgentApproval(
    idOrSlug: string,
    approvalId: string,
    body: DecideApprovalRequest,
  ): Promise<AgentApprovalRequest> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/approvals/${encodeURIComponent(approvalId)}/decide/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: { body: JSON.stringify(body) },
    });
    return (await response.json()) as AgentApprovalRequest;
  }

  /** Lists revisions for an application (newest first, paginated). */
  async listAgentRevisions(idOrSlug: string): Promise<AgentRevision[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/`;
    const url = new URL(`${this.api.baseUrl}${path}?limit=100`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as { results?: AgentRevision[] };
    return data.results ?? [];
  }

  /** Fetches a single revision by id; null if not found. */
  async getAgentRevision(
    idOrSlug: string,
    revisionId: string,
  ): Promise<AgentRevision | null> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path,
      });
      return (await response.json()) as AgentRevision;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("[404]") || msg.includes("[403]")) {
        return null;
      }
      throw error;
    }
  }

  /**
   * Mint a short-lived preview token (HS256 JWT) for a non-live revision. The
   * token is sent to the ingress on /run /send /listen /cancel via
   * `X-Agent-Preview-Token` (alongside the usual bearer) and authorizes those
   * calls to route against this specific revision instead of `live_revision`.
   * The response also self-describes the per-trigger ingress URLs the caller
   * should hit (`endpoints`) so the client never has to construct preview URLs
   * by string-mangling `ingress_base_url`.
   *
   * Note the Django route: app-level path with the revision as a query param,
   * NOT nested under /revisions/{id}/.
   */
  async mintAgentPreviewToken(
    idOrSlug: string,
    revisionId: string,
  ): Promise<AgentPreviewToken> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/preview-token/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("revision_id", revisionId);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
    });
    return (await response.json()) as AgentPreviewToken;
  }

  /**
   * Atomically create a fresh draft revision under this app, seeded with the
   * full bundle of `sourceRevisionId`. The standard "edit an immutable
   * revision" exit: ready/live/archived bundles are stamped and locked, so
   * iterating on them requires forking to a new draft first. Both ids are
   * UUIDs; the app's `slug` is not accepted here (the body needs the UUID).
   */
  async createAgentDraftRevisionFrom(
    applicationId: string,
    sourceRevisionId: string,
  ): Promise<AgentRevision> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(applicationId)}/revisions/new_draft/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify({
          application_id: applicationId,
          source_revision_id: sourceRevisionId,
        }),
      },
    });
    // new_draft wraps the created revision: `{ revision, source_revision_id }`.
    const data = (await response.json()) as { revision: AgentRevision };
    return data.revision;
  }

  /** The served-model catalog + curated auto-level → model map (project-agnostic;
   * proxies the AI gateway catalog). Powers the config-pane model browser. */
  async getAgentModelCatalog(): Promise<ModelCatalog> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}models/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    return (await response.json()) as ModelCatalog;
  }

  /** Update a draft revision's spec (PATCH). Draft-only on the server — a
   * ready/live spec is frozen. Replaces `spec` wholesale, so callers send the
   * full updated spec. Returns the updated revision. */
  async updateAgentRevisionSpec(
    idOrSlug: string,
    revisionId: string,
    spec: AgentSpec,
  ): Promise<AgentRevision> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url,
      path,
      overrides: { body: JSON.stringify({ spec }) },
    });
    return (await response.json()) as AgentRevision;
  }

  /** Run a revision lifecycle transition: freeze (draft→ready), promote
   * (ready→live, demoting the old live), or archive. Returns the updated revision. */
  async transitionAgentRevision(
    idOrSlug: string,
    revisionId: string,
    action: "freeze" | "promote" | "archive",
  ): Promise<AgentRevision> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/${action}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
    });
    return (await response.json()) as AgentRevision;
  }

  /**
   * Write a single bundle file on a draft revision. The server accepts
   * `agent.md` and `skills/<id>/SKILL.md` paths only — tool source / schema
   * stay read-only this round. Ready / live / archived revisions return 409.
   */
  async updateAgentDraftBundleFile(
    idOrSlug: string,
    revisionId: string,
    filePath: string,
    content: string,
  ): Promise<AgentRevision> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/bundle/file/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "put",
      url,
      path,
      overrides: {
        body: JSON.stringify({ path: filePath, content }),
      },
    });
    return (await response.json()) as AgentRevision;
  }

  /**
   * Bulk-import a set of `.md` files into a draft revision's bundle — the
   * migration hatch for porting an existing multi-file agent in one paste.
   * Sets `agent_md` if present and merges `skills[]` by id (adds new ids,
   * overwrites bodies for existing ids; skills not mentioned are left alone).
   * Draft-only; ready / live / archived return 409.
   */
  async importAgentDraftBundle(
    idOrSlug: string,
    revisionId: string,
    body: {
      agent_md?: string;
      skills?: { id: string; description?: string; body: string }[];
    },
  ): Promise<AgentRevision> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/bundle/import/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify(body),
      },
    });
    return (await response.json()) as AgentRevision;
  }

  /**
   * A revision's bundle, flattened to per-file rows. The server returns a typed
   * `{ bundle: { agent_md, skills[], tools[] } }`; we expand it to the canonical
   * file paths the explorer renders (agent.md, skills/<id>/SKILL.md,
   * tools/<id>/source.ts, tools/<id>/schema.json).
   */
  async getAgentRevisionBundle(
    idOrSlug: string,
    revisionId: string,
  ): Promise<BundleFile[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/bundle/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      bundle?: {
        agent_md?: string;
        skills?: { id: string; description?: string; body: string }[];
        tools?: {
          id: string;
          description?: string;
          args_schema?: Record<string, unknown>;
          source: string;
        }[];
      };
    };
    const bundle = data.bundle ?? {};
    const out: BundleFile[] = [];
    if (bundle.agent_md !== undefined) {
      out.push({
        path: "agent.md",
        content: bundle.agent_md,
        language: "markdown",
      });
    }
    for (const skill of bundle.skills ?? []) {
      out.push({
        path: `skills/${skill.id}/SKILL.md`,
        content: skill.body,
        language: "markdown",
      });
    }
    for (const tool of bundle.tools ?? []) {
      out.push({
        path: `tools/${tool.id}/source.ts`,
        content: tool.source,
        language: "typescript",
      });
      out.push({
        path: `tools/${tool.id}/schema.json`,
        content: JSON.stringify(
          { description: tool.description, args_schema: tool.args_schema },
          null,
          2,
        ),
        language: "json",
      });
    }
    out.sort((a, b) => a.path.localeCompare(b.path));
    return out;
  }

  /**
   * Author/compile one custom tool on a draft revision (PUT). Draft-only —
   * ready/live/archived bundles are sealed and the server returns a conflict.
   * A compile failure (HTTP 422) is returned as a typed `{ ok: false }` result
   * carrying `errors`, so the caller renders diagnostics inline against the
   * source rather than surfacing a generic failure; other non-2xx (400
   * invalid_request, 409 sealed revision, …) still throw.
   */
  async putRevisionTool(
    idOrSlug: string,
    revisionId: string,
    toolId: string,
    body: WriteToolRequest,
  ): Promise<WriteToolResult> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/tools/${encodeURIComponent(toolId)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    try {
      const response = await this.api.fetcher.fetch({
        method: "put",
        url,
        path,
        overrides: { body: JSON.stringify(body) },
      });
      const data = (await response.json()) as {
        tool_id: string;
        capabilities: ToolCapabilities;
      };
      return {
        ok: true,
        tool_id: data.tool_id,
        capabilities: data.capabilities,
      };
    } catch (error) {
      const failure = parseFailedRequest(error);
      if (
        failure?.status === 422 &&
        isObjectRecord(failure.body) &&
        failure.body.error === "tool_compile_failed"
      ) {
        return {
          ok: false,
          error: "tool_compile_failed",
          tool_id: optionalString(failure.body.tool_id) ?? toolId,
          errors: Array.isArray(failure.body.errors)
            ? (failure.body.errors as ToolCompileError[])
            : [],
        };
      }
      throw error;
    }
  }

  /**
   * Remove one custom tool from a draft revision (draft-only). A 404
   * (tool_not_found) is treated as success — the tool is already gone, which is
   * the desired end state.
   */
  async deleteRevisionTool(
    idOrSlug: string,
    revisionId: string,
    toolId: string,
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/tools/${encodeURIComponent(toolId)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    try {
      await this.api.fetcher.fetch({ method: "delete", url, path });
    } catch (error) {
      const failure = parseFailedRequest(error);
      if (failure?.status === 404) {
        return;
      }
      throw error;
    }
  }

  /**
   * Execute a persisted tool once in a sandbox (POST …/dry_run). The envelope's
   * `ok` is authoritative: a tool-side failure is HTTP 200 with `ok: false`, so
   * both 2xx and 500 return `{ outcome: "completed", envelope }` and the caller
   * reads `error.code`/`message` from the body. Throttling (429) and an
   * unconfigured backend (503) are returned as distinct outcomes — never thrown,
   * never retried, since dry-run is interactive and process-capped.
   */
  async dryRunRevisionTool(
    idOrSlug: string,
    revisionId: string,
    toolId: string,
    body: DryRunToolRequest,
  ): Promise<DryRunToolResult> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/tools/${encodeURIComponent(toolId)}/dry_run/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    try {
      const response = await this.api.fetcher.fetch({
        method: "post",
        url,
        path,
        overrides: { body: JSON.stringify(body) },
      });
      return {
        outcome: "completed",
        envelope: (await response.json()) as DryRunToolEnvelope,
      };
    } catch (error) {
      const failure = parseFailedRequest(error);
      // A 500 still carries the envelope (ok:false + error.code/duration_ms) —
      // surface it as completed so infra failures read like any tool failure.
      if (
        failure?.status === 500 &&
        isObjectRecord(failure.body) &&
        "ok" in failure.body
      ) {
        return {
          outcome: "completed",
          envelope: failure.body as unknown as DryRunToolEnvelope,
        };
      }
      if (failure?.status === 429) {
        const max = isObjectRecord(failure.body)
          ? failure.body.max_concurrent
          : undefined;
        // Omit rather than default to 0 — "0 runs in flight" would be a
        // misleading count for a throttle.
        return {
          outcome: "throttled",
          max_concurrent: typeof max === "number" ? max : undefined,
        };
      }
      if (failure?.status === 503) {
        return { outcome: "unavailable" };
      }
      throw error;
    }
  }

  /**
   * The Slack app manifest derived from a revision's slack trigger + tools,
   * plus the live Event/Interactivity request URLs and setup notes.
   */
  async getAgentSlackManifest(
    idOrSlug: string,
    revisionId: string,
  ): Promise<AgentSlackManifest> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/slack_manifest/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    return (await response.json()) as AgentSlackManifest;
  }

  /** Fire a cron trigger out-of-band; returns the created session id. */
  async fireAgentCron(
    idOrSlug: string,
    revisionId: string,
    cronName: string,
    requestId?: string,
  ): Promise<{ session_id: string }> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/cron/fire/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify({
          cron_name: cronName,
          ...(requestId ? { request_id: requestId } : {}),
        }),
      },
    });
    return (await response.json()) as { session_id: string };
  }

  /**
   * The names of env keys currently set on a revision (values never returned).
   * Env keys are scoped to a revision, so each revision carries its own secret
   * set.
   */
  async listAgentEnvKeys(
    idOrSlug: string,
    revisionId: string,
  ): Promise<string[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/env_keys/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      keys?: string[];
      results?: string[];
    };
    return data.keys ?? data.results ?? [];
  }

  /** Set or rotate one encrypted env key on a revision. The value is write-only. */
  async setAgentEnvKey(
    idOrSlug: string,
    revisionId: string,
    key: string,
    value: string,
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/env_keys/${encodeURIComponent(key)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    await this.api.fetcher.fetch({
      method: "put",
      url,
      path,
      overrides: { body: JSON.stringify({ value }) },
    });
  }

  /** Clear one encrypted env key on a revision. No-op server-side if it isn't set. */
  async clearAgentEnvKey(
    idOrSlug: string,
    revisionId: string,
    key: string,
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/revisions/${encodeURIComponent(revisionId)}/env_keys/${encodeURIComponent(key)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    await this.api.fetcher.fetch({ method: "delete", url, path });
  }

  private agentMemoryPath(teamId: number, idOrSlug: string): string {
    return `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/memory`;
  }

  /** Pre-aggregated folder tree of the agent's memory store. */
  async getAgentMemoryTree(idOrSlug: string): Promise<AgentMemoryTreeNode> {
    const teamId = await this.getTeamId();
    const path = `${this.agentMemoryPath(teamId, idOrSlug)}/tree/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as { root?: AgentMemoryTreeNode };
    return data.root ?? { name: "root", type: "folder", children: [] };
  }

  /** Read one memory file (header + content). */
  async readAgentMemoryFile(
    idOrSlug: string,
    filePath: string,
  ): Promise<AgentMemoryFile> {
    const teamId = await this.getTeamId();
    const path = `${this.agentMemoryPath(teamId, idOrSlug)}/files/by_path/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("path", filePath);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    return (await response.json()) as AgentMemoryFile;
  }

  /** BM25 full-text search across the agent's memory. */
  async searchAgentMemory(
    idOrSlug: string,
    query: string,
    limit?: number,
  ): Promise<AgentMemorySearchResult[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentMemoryPath(teamId, idOrSlug)}/search/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("q", query);
    if (limit != null) url.searchParams.set("limit", String(limit));
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      results?: AgentMemorySearchResult[];
    };
    return data.results ?? [];
  }

  /** List the agent's JSONL reference tables. */
  async listAgentMemoryTables(
    idOrSlug: string,
  ): Promise<AgentMemoryTableHeader[]> {
    const teamId = await this.getTeamId();
    const path = `${this.agentMemoryPath(teamId, idOrSlug)}/tables/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      tables?: AgentMemoryTableHeader[];
    };
    return data.tables ?? [];
  }

  /** Read rows from one memory table. */
  async readAgentMemoryTable(
    idOrSlug: string,
    name: string,
    limit?: number,
  ): Promise<AgentMemoryTableRows> {
    const teamId = await this.getTeamId();
    const path = `${this.agentMemoryPath(teamId, idOrSlug)}/tables/${encodeURIComponent(name)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (limit != null) url.searchParams.set("limit", String(limit));
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    return (await response.json()) as AgentMemoryTableRows;
  }

  // --- Users / connections --------------------------------------------------
  // The agent's end-users (`agent_user`) and their linked external identities
  // (`agent_identity_credential`). Connection metadata only — encrypted tokens
  // never cross this boundary. Proxied Django → janitor → runtime store, same
  // shape as the memory endpoints above.

  /** List the agent's end-users, each with their linked connections. */
  async listAgentUsers(idOrSlug: string): Promise<AgentUsersListResponse> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/users/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    // The fetcher doesn't throw on non-2xx — surface a genuine failure so the
    // pane shows its error branch rather than masking it as "no users yet"
    // (a non-2xx that still returns JSON would otherwise coalesce to `[]`).
    if (!response.ok) {
      throw new Error(`Failed to load agent users: ${response.status}`);
    }
    const data = (await response.json()) as Partial<AgentUsersListResponse>;
    return { results: data.results ?? [], count: data.count ?? 0 };
  }

  /** Revoke one linked connection for an agent user (kept for audit, not deleted). */
  async deleteAgentUserConnection(
    idOrSlug: string,
    agentUserId: string,
    provider: string,
  ): Promise<void> {
    const teamId = await this.getTeamId();
    const path = `${this.agentApplicationsPath(teamId)}${encodeURIComponent(idOrSlug)}/users/${encodeURIComponent(agentUserId)}/connections/${encodeURIComponent(provider)}/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url,
      path,
    });
    // The fetcher doesn't throw on non-2xx. Revoke is a destructive, audited
    // action — fail loudly so the caller's onError fires instead of a false
    // "Connection revoked" success. 404 is treated as already-gone (idempotent).
    if (!response.ok && response.status !== 404) {
      throw new Error(`Failed to revoke connection: ${response.status}`);
    }
  }

  // --- Live chat (agent-ingress) -------------------------------------------
  // These hit the agent's ingress host (`ingress_base_url`, which already
  // includes `/agents/<slug>`), not the PostHog API. The shared fetcher
  // attaches the same bearer regardless of host, so no proxy is needed (unlike
  // the console, which proxied only because browser EventSource can't set
  // an Authorization header — `fetch` can).
  //
  // `previewToken`, when present, scopes the call to a non-live revision via
  // `X-Agent-Preview-Token`. The fetcher merges `parameters.header` into the
  // built headers (so the bearer survives) — never put preview-token into
  // `overrides.headers`, which replaces the whole headers object.

  /** Start a chat session; returns the new session id. */
  async runAgentSession(
    ingressBaseUrl: string,
    message: string,
    previewToken?: string | null,
    supportedClientTools?: readonly string[],
  ): Promise<{ session_id: string; resumed?: boolean }> {
    const url = new URL(`${ingressBaseUrl.replace(/\/$/, "")}/run`);
    // `supported_client_tools`: the kind:'client' tool ids this client can
    // execute this session, so the runner exposes only those to the model.
    const body: Record<string, unknown> = { message };
    if (supportedClientTools && supportedClientTools.length > 0) {
      body.supported_client_tools = supportedClientTools;
    }
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: { body: JSON.stringify(body) },
    });
    return (await response.json()) as { session_id: string; resumed?: boolean };
  }

  /** Send a follow-up user message to an open session. */
  async sendAgentMessage(
    ingressBaseUrl: string,
    sessionId: string,
    message: string,
    previewToken?: string | null,
  ): Promise<void> {
    const url = new URL(`${ingressBaseUrl.replace(/\/$/, "")}/send`);
    await this.api.fetcher.fetch({
      method: "post",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: { body: JSON.stringify({ session_id: sessionId, message }) },
    });
  }

  /**
   * Decide a `principal`-type tool approval at the ingress, as the session
   * principal. The ingress authenticates the preview token / passthrough bearer
   * and enforces principal-match — this is the session owner clearing their own
   * gated call, not the owner-console (Django) decision path. `agent`-type
   * approvals are NOT decidable here; they go through `decideAgentApproval`.
   */
  async decideAgentApprovalViaIngress(
    ingressBaseUrl: string,
    approvalId: string,
    body: DecideApprovalRequest,
    previewToken?: string | null,
  ): Promise<{ ok: boolean; state: string }> {
    const url = new URL(
      `${ingressBaseUrl.replace(/\/$/, "")}/approvals/${encodeURIComponent(approvalId)}/decide`,
    );
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: { body: JSON.stringify(body) },
    });
    return (await response.json()) as { ok: boolean; state: string };
  }

  /**
   * Fetch one approval by id straight from the agent's ingress, authenticated as
   * the session principal (the shared bearer). Powers the deep-link approval
   * modal: no project-scoped lookup, so it resolves from any project. Returns
   * null on 404/403 (gone, or the caller isn't the session principal).
   */
  async getAgentApprovalViaIngress(
    ingressBaseUrl: string,
    approvalId: string,
    previewToken?: string | null,
  ): Promise<AgentApprovalRequest | null> {
    const url = new URL(
      `${ingressBaseUrl.replace(/\/$/, "")}/approvals/${encodeURIComponent(approvalId)}`,
    );
    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: url.pathname,
        parameters: previewTokenHeader(previewToken),
      });
      return (await response.json()) as AgentApprovalRequest;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("[404]") || msg.includes("[403]")) {
        return null;
      }
      throw error;
    }
  }

  /**
   * Fetch a session's transcript straight from the agent's ingress, authenticated
   * as the session principal — cross-project transcript reload (dock reopen, a
   * web chat-list opening a past session, repainting a pending-approval card
   * after a reconnect). Mirrors `getAgentApplicationSession`'s shape; `lastN`
   * trims to the trailing messages. Null on 404/403.
   */
  async getAgentSessionViaIngress(
    ingressBaseUrl: string,
    sessionId: string,
    lastN?: number,
    previewToken?: string | null,
  ): Promise<AgentApplicationSessionDetail | null> {
    const url = new URL(
      `${ingressBaseUrl.replace(/\/$/, "")}/sessions/${encodeURIComponent(sessionId)}`,
    );
    if (lastN != null) {
      url.searchParams.set("last_n", String(lastN));
    }
    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url,
        path: url.pathname,
        parameters: previewTokenHeader(previewToken),
      });
      return (await response.json()) as AgentApplicationSessionDetail;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("[404]") || msg.includes("[403]")) {
        return null;
      }
      throw error;
    }
  }

  /** Return a client-tool result to an open session. */
  async sendAgentClientToolResult(
    ingressBaseUrl: string,
    sessionId: string,
    callId: string,
    outcome: { result?: unknown; error?: string },
    previewToken?: string | null,
  ): Promise<void> {
    const url = new URL(
      `${ingressBaseUrl.replace(/\/$/, "")}/client_tool_result`,
    );
    await this.api.fetcher.fetch({
      method: "post",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: {
        body: JSON.stringify({
          session_id: sessionId,
          call_id: callId,
          ...outcome,
        }),
      },
    });
  }

  /**
   * Return an *interactive* client-tool outcome (e.g. `set_secret`). Unlike the
   * sync `/client_tool_result` path, the server-side tool returned `queued` and
   * parked the session; posting the outcome via `/send` (as a `client_tool_result`
   * marker) wakes it on a fresh turn. Exactly one of `result` / `error` is set.
   */
  async sendAgentInteractiveToolResult(
    ingressBaseUrl: string,
    sessionId: string,
    callId: string,
    outcome: { result: Record<string, unknown> } | { error: string },
    previewToken?: string | null,
  ): Promise<void> {
    const url = new URL(`${ingressBaseUrl.replace(/\/$/, "")}/send`);
    const clientToolResult =
      "error" in outcome
        ? { call_id: callId, error: outcome.error }
        : { call_id: callId, result: outcome.result };
    await this.api.fetcher.fetch({
      method: "post",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: {
        body: JSON.stringify({
          session_id: sessionId,
          client_tool_result: clientToolResult,
        }),
      },
    });
  }

  /** Cancel an open session (terminal). */
  async cancelAgentSession(
    ingressBaseUrl: string,
    sessionId: string,
    previewToken?: string | null,
  ): Promise<void> {
    const url = new URL(`${ingressBaseUrl.replace(/\/$/, "")}/cancel`);
    await this.api.fetcher.fetch({
      method: "post",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: { body: JSON.stringify({ session_id: sessionId }) },
    });
  }

  /**
   * Stream a session's SSE events as an async iterator. Reads the raw response
   * body and parses `text/event-stream` frames into `AgentSessionEvent`s.
   */
  async *streamAgentSession(
    ingressBaseUrl: string,
    sessionId: string,
    signal?: AbortSignal,
    previewToken?: string | null,
  ): AsyncGenerator<AgentSessionEvent> {
    const url = new URL(`${ingressBaseUrl.replace(/\/$/, "")}/listen`);
    url.searchParams.set("session_id", sessionId);
    // NB: only `signal` in overrides. Passing `headers` here would replace the
    // fetcher's Authorization header (it spreads overrides over the built
    // headers), which 401s the stream. The preview token rides on
    // `parameters.header` — merged in, not replacing. /listen streams SSE
    // without an explicit Accept header.
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: url.pathname,
      parameters: previewTokenHeader(previewToken),
      overrides: { signal },
    });
    if (!response.body) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Frames are separated by a blank line.
        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const data = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (data) {
            try {
              yield JSON.parse(data) as AgentSessionEvent;
            } catch {
              // Skip unparseable frames (keep-alives, comments).
            }
          }
          sep = buffer.indexOf("\n\n");
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  /** Live (non-terminal) sessions across every agent on the team. */
  async listAgentFleetLiveSessions(
    limit?: number,
  ): Promise<AgentFleetLiveSessionsResponse> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/agent_fleet/live_sessions/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (limit != null) {
      url.searchParams.set("limit", String(limit));
    }
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      results?: AgentFleetLiveSessionsResponse["results"];
    };
    return { results: data.results ?? [] };
  }

  /** All tool-approval requests across the team (team-admin only). */
  async listAgentFleetApprovals(
    params?: AgentApprovalsListParams,
  ): Promise<AgentApprovalRequest[]> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/agent_fleet/approvals/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    if (params?.state) {
      url.searchParams.set("state", params.state);
    }
    if (params?.agent_id) {
      url.searchParams.set("agent_id", params.agent_id);
    }
    if (params?.limit != null) {
      url.searchParams.set("limit", String(params.limit));
    }
    if (params?.offset != null) {
      url.searchParams.set("offset", String(params.offset));
    }
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    const data = (await response.json()) as {
      results?: AgentApprovalRequest[];
    };
    return data.results ?? [];
  }

  /**
   * Runs a read-only HogQL query against the team's project and returns the raw
   * result grid. Backs the agent observability rollups (`$ai_*` events the
   * runner captures into this team's own project). The endpoint can answer 200
   * with an `error` field; that's surfaced as a throw.
   */
  async runHogQLQuery(query: string): Promise<HogQLGrid> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/query/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify({ query: { kind: "HogQLQuery", query } }),
      },
    });
    const data = (await response.json()) as {
      results?: unknown[][];
      columns?: string[];
      error?: string | null;
    };
    if (data.error) {
      throw new Error(data.error);
    }
    return { results: data.results ?? [], columns: data.columns ?? [] };
  }

  /**
   * Agent observability rollup over the agents' `$ai_*` events — KPIs (spend,
   * sessions, failure rate, p95), a 14-day daily trend + WoW deltas, and
   * spend-by-agent / cost-by-model / tool-reliability breakdowns. Pass an
   * `applicationId` (the agent's UUID) to scope it to a single agent; omit it
   * for the fleet-wide board.
   *
   * The five panels are independent HogQL round-trips fired in parallel. The
   * KPI query is the gate — a systemic failure (auth, bad query) rejects the
   * whole call so the UI shows an error rather than a silently-empty board; the
   * secondary panels degrade to empty individually. The fleet board also reads
   * the agent list to label per-agent rows by name.
   */
  async getAgentAnalytics(applicationId?: string): Promise<AgentAnalyticsData> {
    const queries = buildAgentAnalyticsQueries(applicationId);
    const empty: HogQLGrid = { results: [], columns: [] };
    const [agents, kpi, daily, perAgent, byModel, toolErrors] =
      await Promise.all([
        applicationId
          ? Promise.resolve<AgentApplication[]>([])
          : this.listAgentApplications().catch(() => [] as AgentApplication[]),
        this.runHogQLQuery(queries.kpi),
        this.runHogQLQuery(queries.daily).catch(() => empty),
        this.runHogQLQuery(queries.perAgent).catch(() => empty),
        this.runHogQLQuery(queries.byModel).catch(() => empty),
        this.runHogQLQuery(queries.toolErrors).catch(() => empty),
      ]);
    const nameById = new Map(agents.map((a) => [a.id, a.name]));
    return shapeAgentAnalytics(
      { kpi, daily, perAgent, byModel, toolErrors },
      nameById,
    );
  }
}
