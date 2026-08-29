import "./generated.augment";
import type {
  Adapter,
  CloudMcpServerRelayDesignation,
  CloudRunSource,
  ExecutionMode,
  McpServerConnection,
  PrAuthorshipMode,
  SourceProduct,
  SourceType,
  StoredLogEntry,
  TaskRunArtifactMetadata,
} from "@posthog/shared";
import {
  buildCloudTaskConfigOptions,
  type CloudTaskConfigOption,
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  getCloudTaskGatewayUrl,
  isSupportedReasoningEffort,
  normalizeGatewayModelsResponse,
  resolveCloudInitialPermissionMode,
} from "@posthog/shared";
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
  ProvisionedTaskChannels,
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
  SignalReportRefundReason,
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
  TaskActivityMarkReadResult,
  TaskActivityPage,
  TaskActivityReadMarker,
  TaskChannel,
  TaskMention,
  TaskRun,
  TaskRunArtefact,
  TaskRunArtifact,
  TaskThreadMessage,
  UserBasic,
} from "@posthog/shared/domain-types";
import { buildPosthogProjectHeaderRecord } from "@posthog/shared/posthog-property-headers";
import {
  activitySection,
  compactCount,
  dailySparkLabels,
  dailySparkPoints,
  decorateFlagPreview,
  decorateSurveyPreview,
  type EvidencePreview,
  type ExperimentMetricQueryResult,
  experimentMetricQueries,
  formatDay,
  gridRows,
  hogqlEscape,
  shapeActionPreview,
  shapeCohortPreview,
  shapeDashboardPreview,
  shapeErrorIssuePreview,
  shapeEvaluationPreview,
  shapeEventDefinitionPreview,
  shapeExperimentExposureChart,
  shapeExperimentPreview,
  shapeExperimentResults,
  shapeFlagPreview,
  shapePersonPreview,
  shapeRecordingPreview,
  shapeSurveyPreview,
  shapeTicketPreview,
  shapeTracePreview,
} from "./evidence-previews";
import {
  ApiRequestError,
  buildApiFetcher,
  type FetchImplementation,
  requestErrorStatus,
} from "./fetcher";
import { createApiClient, type Schemas } from "./generated";
import type {
  McpAgentGrantScope,
  McpAuditCounts,
  McpAuditEvent,
  McpAuditPage,
  McpAuditQuickFilter,
  McpGatewayInstallSharingOptions,
  McpGatewayMemberSummary,
  McpGatewayPolicyScope,
  McpGatewayServer,
  McpGatewayServerUpdate,
  McpResolvedToolPolicy,
  McpServiceAccount,
  McpServiceAccountStatus,
  McpServiceAccountWithToken,
  McpToolPolicyEntry,
  TeamMcpGatewayConfig,
  TeamMcpGatewayConfigUpdate,
} from "./mcp-gateway";
import type { SpendAnalysisResponse } from "./spend-analysis";
import { parseUserSpendLimit, type UserSpendLimit } from "./spend-limit";
import {
  normalizeTaskResponse,
  normalizeTaskRunArtifact,
  normalizeTaskRunResponse,
  type TaskRunArtifactDTO,
} from "./task-normalization";

interface HogQLGrid {
  results: unknown[][];
  columns: string[];
}

export type * from "./mcp-gateway";
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

export interface PostHogAPIClientOptions {
  fetch?: FetchImplementation;
  appVersion?: string;
  userAgent?: string | null;
  githubConnectFrom?: string;
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
export const DESKTOP_BILLING_LIMIT_ERROR_CODE =
  "posthog_code_billing_limit_exceeded";

export const SESSION_LOGS_MAX_PAGE_SIZE = 5000;
export const SESSION_LOGS_PAGE_TIMEOUT_MS = 30_000;

export interface TaskRunSessionLogsResult {
  entries: StoredLogEntry[];
  complete: boolean;
  truncatedHeadCount: number;
}

type SessionLogsPage =
  | { ok: true; entries: StoredLogEntry[]; headers: Headers }
  | { ok: false; status: number; statusText: string };

export interface TaskRunSessionLogsPage {
  entries: StoredLogEntry[];
  hasMore: boolean;
  matchingCount: number | null;
}

export interface TaskUsage {
  token_cost_usd: number;
  compute_cost_usd: number;
  total_cost_usd: number;
}

export interface TaskListOptions {
  repository?: string;
  createdBy?: number;
  originProduct?: string;
  internal?: boolean;
  channel?: string;
  /** Case-insensitive substring match over task title, description, and number. */
  search?: string;
  /** Filter by the status of the task's most recent run. */
  status?: string;
  /** Filter by the state of the latest run's pull request (open/draft/merged/closed). */
  prState?: string;
  /** Filter by the CI rollup on the latest run's pull request (passing/failing/pending/none). */
  ciStatus?: string;
  /** List only tasks the requesting user has pinned. */
  pinned?: boolean;
  /** Filter to tasks with a thread comment from this user ID. */
  commentedBy?: number;
  /** Filter to tasks whose thread mentions this user ID. */
  mentions?: number;
  /** List only archived tasks; the server excludes them by default. */
  archived?: boolean;
  /** Caller-side cap for surfaces that only show the newest few. */
  limit?: number;
  /**
   * Which end of the list the page is cut from. A surface that asks for a short page and means
   * "what has been happening here" has to say so, or the server hands back the newest-created
   * few and a long-running session never makes the page.
   */
  ordering?: "-last_activity_at" | "-created_at";
  /** Zero-based offset for fetching a later task-list page. */
  offset?: number;
}

export interface TaskSearchResult {
  id: string;
  kind: "task" | "pull_request" | "artifact" | "channel";
  title: string;
  subtitle: string;
  task_id: string | null;
  task_run_id: string | null;
  channel_id: string | null;
  metadata: Record<string, unknown>;
}

export interface TaskSessionStorageAccess {
  id: string;
  download_url: string | null;
  content_sha256: string | null;
}

/**
 * The commentable resources this client knows how to address. `scope` is a
 * free-form column on the backend `Comment` model, so adding a resource is a
 * new member here plus a caller — no migration and no endpoint.
 */
export type CommentScope = "task_artifact" | "desktop_canvas" | "task";

/** Named `Resource*` so it never collides with the DOM's global `Comment`.
 * Optimistic rows do not have a server version yet, while item_context is a
 * real JSON value despite the generated serializer's historically narrow type. */
export type ResourceComment = Omit<Schemas.Comment, "version"> & {
  version?: number;
};

export interface CreateResourceCommentRequest {
  scope: CommentScope;
  itemId: string;
  content: string;
  context: unknown;
  sourceCommentId?: string;
  mentions?: number[];
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

export type GithubInstallationStatus = "connected" | "unavailable";

export interface UserGitHubIntegration {
  id: string;
  kind: "github";
  installation_id: string;
  repository_selection?: string | null;
  account?: {
    type?: string | null;
    name?: string | null;
  } | null;
  github_login?: string | null;
  uses_shared_installation?: boolean;
  /** False when disconnecting would also uninstall the App from GitHub. */
  installation_shared?: boolean;
  installation_status?: GithubInstallationStatus;
  created_at?: string;
}

/** `unidentified` means the requester could not be resolved, so approval can never
 * be detected and the user has to restart the connect flow. */
export type GithubInstallRequestStatus =
  | "pending"
  | "approved"
  | "unidentified";

/** A personal GitHub App install awaiting (or granted) org-owner approval; the
 * durable server-side counterpart to the in-flight connect spinner. Mirrors
 * `GitHubInstallRequest` on the backend. */
export interface GithubInstallRequestItem {
  id: string;
  github_login: string;
  status: GithubInstallRequestStatus;
  installation_id: string | null;
  account_login?: string | null;
  account_type?: string | null;
  requested_at: string;
  resolved_at: string | null;
}

export interface GithubInstallRequestsResponse {
  results: GithubInstallRequestItem[];
  /** App install page with no PostHog state, for an org owner to open. */
  install_url?: string | null;
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

/**
 * Lifecycle state the coordinator keeps alongside `enabled`:
 * - `active` – running on its schedule.
 * - `pending_pause` – still running, but flagged by the inactivity sweep and
 *   due to be paused unless something changes.
 * - `paused_by_user` – a person switched it off; the system never overrides it.
 * - `paused_by_system` – the platform switched it off, see `pause_reason`.
 */
export type ScoutLifecycleStatus =
  | "active"
  | "pending_pause"
  | "paused_by_user"
  | "paused_by_system";

/**
 * Why the system warned or paused a scout: `ignored` (its findings went
 * unacted on), `no_output` (it stopped emitting anything), or
 * `repeated_failures` (its runs kept erroring).
 */
export type ScoutPauseReason = "ignored" | "no_output" | "repeated_failures";

export interface ScoutConfig {
  id: string;
  skill_name: string;
  enabled: boolean;
  /** False means dry-run: the scout runs but findings are not emitted. */
  emit: boolean;
  /**
   * Lifecycle state behind `enabled`. Absent on backends predating the
   * lifecycle fields, in which case `enabled` is all there is to go on.
   */
  status?: ScoutLifecycleStatus;
  /** Why the system warned or paused the scout; null while it is healthy. */
  pause_reason?: ScoutPauseReason | null;
  /** ISO timestamp of the last `status` transition; null if it never moved. */
  status_changed_at?: string | null;
  /** Runs that failed back to back; trips a `repeated_failures` pause. */
  consecutive_failure_count?: number;
  /**
   * Exempts the scout from the inactivity sweep — both the `ignored` pause and
   * the `no_output` warning. Set on watchdog scouts whose value is staying quiet.
   */
  auto_pause_exempt?: boolean;
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
  /** Non-secret connection settings, e.g. a GitHub source's `repositories`. */
  job_inputs?: Record<string, unknown> | null;
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

export interface ChannelInstructionsUser {
  id?: number;
  uuid?: string;
  first_name?: string;
  last_name?: string | null;
  email?: string;
}

export interface ChannelInstructions {
  channel: string;
  content: string;
  version: number;
  created_at: string;
  created_by: ChannelInstructionsUser | null;
}

export interface ChannelInstructionsVersion {
  channel: string;
  version: number;
  created_at: string;
  created_by: ChannelInstructionsUser | null;
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

export interface PostHogObjectReferenceInput {
  name: string;
  object_kind: string;
  object_id: string;
  source_message_id: string;
}

export interface ContextWikiTree {
  head_sha: string;
  paths: string[];
}

export interface ContextWikiPage {
  path: string;
  content: string;
  head_sha: string;
  updated_at: string;
}

export interface ContextWikiHealthFinding {
  category: string;
  path: string;
  message: string;
}

export interface ContextWikiHealthReport {
  head_sha: string;
  findings: ContextWikiHealthFinding[];
}

export interface ChannelContextWikiPage {
  path: string;
}

// Thrown when PUT /context_layer/pages/ rejects a write because the caller's
// `base_head` is older than the wiki's current head. `currentHead` is the head
// to re-read against before retrying.
export class ContextWikiConflictError extends Error {
  status = 409;
  currentHead: string | null;
  constructor(currentHead: string | null) {
    super("The wiki changed since you started editing");
    this.name = "ContextWikiConflictError";
    this.currentHead = currentHead;
  }
}

// Thrown when a page write fails the wiki's structure lint; `errors` lists the
// violations for inline display.
export class ContextWikiLintError extends Error {
  status = 400;
  errors: string[];
  constructor(detail: string, errors: string[]) {
    super(detail);
    this.name = "ContextWikiLintError";
    this.errors = errors;
  }
}

// Thrown on 403: the organization has private projects, so its wiki is
// deliberately unavailable. Distinct from 404 (wiki never enabled).
export class ContextWikiUnavailableError extends Error {
  status = 403;
  constructor(message: string) {
    super(message);
    this.name = "ContextWikiUnavailableError";
  }
}

/** DRF error bodies carry the human-readable message in `detail`. */
function readDetail(error: ApiRequestError): string {
  const body = error.body as { detail?: string } | null;
  return body?.detail ?? error.message;
}

/**
 * DRF validation failures carry the messages per field, `{ field: [msg] }`,
 * with no top-level `detail`. Flatten them so the server's own wording reaches
 * the toast instead of a bare status text.
 */
function readFieldErrors(error: ApiRequestError): string {
  if (typeof error.body !== "object" || error.body === null) {
    return error.message;
  }
  const record = error.body as Record<string, unknown>;
  if (typeof record.detail === "string") return record.detail;
  const parts = Object.values(record).flatMap((messages) =>
    Array.isArray(messages) ? messages.map(String) : [],
  );
  return parts.length > 0 ? parts.join(" ") : error.message;
}

export interface TaskArtifactUploadRequest {
  name: string;
  type: "output" | "user_attachment" | "skill_bundle";
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
  uploaded_by?: "agent" | "user";
  uploaded_by_user_id?: number;
}

export interface CloudRunOptions {
  adapter?: Adapter;
  piRuntime?: boolean;
  model?: string;
  reasoningLevel?: string;
  contextWindow?: "200k" | "1m";
  fastMode?: boolean;
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
  importedMcpServers?: McpServerConnection[];
  relayedMcpServers?: CloudMcpServerRelayDesignation[];
}

export type CloudRunCommandMethod =
  | "user_message"
  | "permission_response"
  | "set_config_option"
  | "cancel"
  | "close";

export class CloudCommandError extends Error {
  readonly status: number;
  readonly backendError: string | null;
  readonly method: CloudRunCommandMethod;

  constructor(
    method: CloudRunCommandMethod,
    status: number,
    backendError: string | null,
    message: string,
  ) {
    super(message);
    this.name = "CloudCommandError";
    this.method = method;
    this.status = status;
    this.backendError = backendError;
  }

  isSandboxInactive(): boolean {
    const backendError = this.backendError?.toLowerCase();
    return (
      this.status === 404 ||
      backendError?.includes("no active sandbox") === true ||
      backendError?.includes("returned 404") === true
    );
  }
}

function cloudCommandBackendError(payload: unknown): string | null {
  if (typeof payload === "string") return payload || null;
  if (!payload || typeof payload !== "object") return null;

  const error = "error" in payload ? payload.error : null;
  if (typeof error === "string") return error || null;
  if (error && typeof error === "object" && "message" in error) {
    return typeof error.message === "string" ? error.message : null;
  }
  if ("message" in payload && typeof payload.message === "string") {
    return payload.message;
  }
  return null;
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
  }
  if (options?.model && (options.adapter || options.piRuntime)) {
    body.model = options.model;
  }
  if (options?.reasoningLevel && (options.adapter || options.piRuntime)) {
    if (!options.model) {
      throw new Error(
        "A cloud reasoning level requires a model to be selected.",
      );
    }
    if (
      options.adapter &&
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
  if (options?.adapter && options.contextWindow) {
    body.context_window = options.contextWindow;
  }
  if (options?.adapter && options.fastMode !== undefined) {
    body.fast_mode = options.fastMode;
  }
  if (options?.adapter && options.initialPermissionMode) {
    body.initial_permission_mode = resolveCloudInitialPermissionMode(
      options.adapter,
      options.initialPermissionMode,
    );
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
  if (options?.autoPublish !== undefined) {
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

// DRF's generic placeholder for "no route matched" and an unhandled NotFound
// alike — never a business-specific message, so it's less actionable than the
// endpoint's own fallback plus status code.
const DRF_GENERIC_NOT_FOUND_DETAIL = "Not found.";

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
    if (
      typeof message === "string" &&
      message.trim() &&
      message !== DRF_GENERIC_NOT_FOUND_DETAIL
    ) {
      return message;
    }
  } catch {
    // Non-JSON body — fall through to the status-based fallback.
  }
  return `${fallback} (HTTP ${match[1]})`;
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

export class PostHogAPIClient {
  private api: ReturnType<typeof createApiClient>;
  private _teamId: number | null = null;
  private githubConnectFrom: string;
  private readonly apiHost: string;

  constructor(
    apiHost: string,
    getAccessToken: () => Promise<string>,
    refreshAccessToken: () => Promise<string>,
    teamId?: number,
    options: PostHogAPIClientOptions = {},
  ) {
    const baseUrl = apiHost.endsWith("/") ? apiHost.slice(0, -1) : apiHost;
    this.apiHost = baseUrl;
    this.githubConnectFrom = options.githubConnectFrom ?? "posthog_code";
    this.api = createApiClient(
      buildApiFetcher({
        getAccessToken,
        refreshAccessToken,
        appVersion: options.appVersion ?? clientAppVersion,
        fetch: options.fetch,
        userAgent: options.userAgent,
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

  async getCloudTaskConfigOptions(
    adapter: Adapter = "claude",
  ): Promise<CloudTaskConfigOption[]> {
    const teamId = await this.getTeamId();
    const url = new URL(`${getCloudTaskGatewayUrl(this.apiHost)}/v1/models`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: url.pathname,
      parameters: {
        header: buildPosthogProjectHeaderRecord(teamId),
      },
    });
    return buildCloudTaskConfigOptions(
      normalizeGatewayModelsResponse(await response.json()),
      adapter,
    );
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
        body: JSON.stringify({
          team_id: id,
          connect_from: this.githubConnectFrom,
        }),
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

  /** `GET /api/users/@me/integrations/github/install_requests/`: installs waiting on a GitHub org owner. */
  async getGithubInstallRequests(): Promise<GithubInstallRequestsResponse> {
    const urlPath = `/api/users/@me/integrations/github/install_requests/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch GitHub install requests: ${response.statusText}`,
      );
    }
    const data =
      (await response.json()) as Partial<GithubInstallRequestsResponse>;
    return {
      results: data.results ?? [],
      install_url: data.install_url ?? null,
    };
  }

  async dismissGithubInstallRequest(requestId: string): Promise<void> {
    const urlPath = `/api/users/@me/integrations/github/install_requests/${encodeURIComponent(requestId)}/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    await this.api.fetcher.fetch({
      method: "delete",
      url,
      path: urlPath,
    });
  }

  /** `DELETE /api/environments/{project}/integrations/{id}/`: any team-level integration (GitHub, Slack, ...). */
  async deleteIntegration(
    projectId: number,
    integrationId: number | string,
  ): Promise<void> {
    await this.api.delete("/api/projects/{project_id}/integrations/{id}/", {
      path: { project_id: projectId.toString(), id: Number(integrationId) },
    });
  }

  /** Emails the project's admins asking them to connect an integration; members only. */
  async requestIntegrationAccess(
    projectId: number,
    body: { kind: string; reason: string },
  ): Promise<void> {
    const urlPath = `/api/environments/${projectId}/integrations/request_access/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: { body: JSON.stringify(body) },
    });
  }

  /** The user's linked Slack identities. Empty until they run the Sign-in-with-Slack flow. */
  async listSlackUserIntegrations(): Promise<
    {
      slack_user_id: string;
      slack_team_id: string;
      slack_team_name: string | null;
    }[]
  > {
    const urlPath = `/api/users/@me/integrations/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    url.searchParams.set("kind", "slack");
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to list Slack integrations: ${response.statusText}`,
      );
    }
    const data = (await response.json()) as {
      results?: {
        slack_user_id: string;
        slack_team_id: string;
        slack_team_name: string | null;
      }[];
    };
    return data.results ?? [];
  }

  /**
   * `POST .../integrations/slack/start`. Returns the Sign-in-with-Slack URL; Slack tells the
   * callback which user authorized, so nobody types a Slack ID.
   */
  async startSlackUserIntegrationConnect(
    teamId?: number,
  ): Promise<{ install_url: string }> {
    const id = teamId ?? (await this.getTeamId());
    const urlPath = `/api/users/@me/integrations/slack/start/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
      overrides: { body: JSON.stringify({ team_id: id }) },
    });
    if (!response.ok) {
      const err = (await response.json().catch(() => ({}))) as {
        detail?: unknown;
      };
      throw new Error(
        typeof err.detail === "string"
          ? err.detail
          : `Failed to start Slack connect: ${response.statusText}`,
      );
    }
    return (await response.json()) as { install_url: string };
  }

  /** Patch the user's server-side notification settings. Merged server-side, so pass only the keys you change. */
  async updateNotificationSettings(
    settings: Record<string, unknown>,
  ): Promise<void> {
    await this.api.patch("/api/users/{uuid}/", {
      path: { uuid: "@me" },
      body: { notification_settings: settings } as Record<string, unknown>,
    });
  }

  async switchOrganization(orgId: string): Promise<void> {
    await this.api.patch("/api/users/{uuid}/", {
      path: { uuid: "@me" },
      body: { set_current_organization: orgId } as Record<string, unknown>,
    });
  }

  async approveAiDataProcessing(organizationId: string): Promise<void> {
    const urlPath = `/api/organizations/${organizationId}/`;
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

  async areDesktopBetaTermsAccepted(organizationId: string): Promise<boolean> {
    const urlPath = `/api/organizations/${organizationId}/desktop_beta_terms/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to check Desktop beta terms: ${response.statusText}`,
      );
    }
    const data = (await response.json()) as {
      is_desktop_beta_terms_accepted: boolean;
    };
    return data.is_desktop_beta_terms_accepted;
  }

  async acceptDesktopBetaTerms(organizationId: string): Promise<void> {
    const urlPath = `/api/organizations/${organizationId}/desktop_beta_terms/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to accept Desktop beta terms: ${response.statusText}`,
      );
    }
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

  async updateScoutConfig(
    projectId: number,
    configId: string,
    updates: {
      /**
       * Flipping this off records a user pause (`status` becomes
       * `paused_by_user`, which the system never overrides); flipping it on
       * resumes the scout from any pause, including a system one.
       */
      enabled?: boolean;
      emit?: boolean;
      run_interval_minutes?: number;
      auto_pause_exempt?: boolean;
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
   * `PATCH .../external_data_sources/{id}/`. `job_inputs` merges into the stored inputs, so
   * changing a GitHub source's repositories only needs `{ repositories: [...] }`.
   */
  async updateExternalDataSource(
    projectId: number,
    sourceId: string,
    payload: { job_inputs: Record<string, unknown> },
  ): Promise<ExternalDataSource> {
    const response = await this.api.patch(
      "/api/projects/{project_id}/external_data_sources/{id}/",
      {
        path: { project_id: projectId.toString(), id: sourceId },
        body: payload as unknown as Schemas.PatchedExternalDataSourceSerializers,
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
          `Failed to update external data source: ${response.statusText}`,
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

  /**
   * Update several of a source's schemas in one request. The backend commits each schema on its
   * own, so one schema failing still applies the rest and the error names the ones it could not
   * save — unlike a client-side loop, where the first failure skips everything after it.
   */
  async bulkUpdateExternalDataSchemas(
    projectId: number,
    sourceId: string,
    schemas: { id: string; should_sync?: boolean; sync_type?: string }[],
  ): Promise<void> {
    const response = await this.api.patch(
      "/api/projects/{project_id}/external_data_sources/{id}/bulk_update_schemas/",
      {
        path: { project_id: projectId.toString(), id: sourceId },
        query: {},
        body: {
          schemas,
        } as unknown as Schemas.PatchedExternalDataSourceBulkUpdateSchemas,
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
          `Failed to update external data schemas: ${response.statusText}`,
      );
    }
  }

  async getTasks(options?: TaskListOptions): Promise<Task[]> {
    return (await this.getTasksPage(options)).tasks;
  }

  async getTasksWithStatus(
    options?: TaskListOptions,
    pagination?: { maxPages?: number },
  ): Promise<{ tasks: Task[]; isComplete: boolean }> {
    const maxPages = pagination?.maxPages ?? 1;
    const pageSize = Math.min(options?.limit ?? 100, 100);
    const tasks: Task[] = [];
    let count = 0;

    for (let pageIndex = 0; pageIndex < maxPages; pageIndex++) {
      const page = await this.getTasksPage({
        ...options,
        limit: pageSize,
        offset: tasks.length,
      });
      tasks.push(...page.tasks);
      count = page.count;
      if (tasks.length >= count) return { tasks, isComplete: true };
      if (page.tasks.length === 0) break;
    }

    return { tasks, isComplete: tasks.length >= count };
  }

  async searchTasks(query: string, limit = 20): Promise<TaskSearchResult[]> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/tasks/search/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("q", query);
    url.searchParams.set("limit", String(limit));
    const response = await this.api.fetcher.fetch({ method: "get", url, path });
    if (!response.ok) {
      throw new Error(`Failed to search tasks: ${response.statusText}`);
    }
    return (await response.json()) as TaskSearchResult[];
  }

  /**
   * The same list with the total behind it, for surfaces that ask for a short
   * page and still have to say how much they are not showing.
   */
  async getTasksPage(
    options?: TaskListOptions,
  ): Promise<{ tasks: Task[]; count: number }> {
    const teamId = await this.getTeamId();
    const params: Record<string, string | number | boolean> = {
      limit: options?.limit ?? 500,
    };

    if (options?.offset !== undefined) {
      params.offset = options.offset;
    }

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

    if (options?.search) {
      params.search = options.search;
    }

    if (options?.status) {
      params.status = options.status;
    }

    if (options?.prState) {
      params.pr_state = options.prState;
    }

    if (options?.ciStatus) {
      params.ci_status = options.ciStatus;
    }

    if (options?.pinned) {
      params.pinned = true;
    }

    if (options?.commentedBy) {
      params.commented_by = options.commentedBy;
    }

    if (options?.mentions) {
      params.mentions = options.mentions;
    }

    if (options?.archived) {
      params.archived = "true";
    }

    if (options?.ordering) {
      params.ordering = options.ordering;
    }

    const data = await this.api.get(`/api/projects/{project_id}/tasks/`, {
      path: { project_id: teamId.toString() },
      query: params,
    });

    const tasks = (data.results ?? []).map((task) =>
      normalizeTaskResponse(task, { teamId }),
    );
    return { tasks, count: data.count ?? tasks.length };
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
    return normalizeTaskResponse(data, { teamId });
  }

  async getTaskUsage(taskId: string): Promise<TaskUsage> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/usage/`;
    const response = await this.api.fetcher.fetch({
      method: "get",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch task usage: ${response.statusText}`);
    }
    return (await response.json()) as TaskUsage;
  }

  async getPinnedTaskIds(): Promise<string[]> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/pinned/`;
    const response = await this.api.fetcher.fetch({
      method: "get",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch pinned tasks: ${response.statusText}`);
    }
    const data = (await response.json()) as { task_ids: string[] };
    return data.task_ids;
  }

  async setTaskPinned(taskId: string, pinned: boolean): Promise<boolean> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/pin/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({ pinned }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to update task pin: ${response.statusText}`);
    }
    const data = (await response.json()) as { pinned: boolean };
    return data.pinned;
  }

  // Handoff is absent from the Desktop-generated client, so use the same raw-fetch path as pin.
  async handoffTask(taskId: string, userId: number): Promise<Task> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/${taskId}/handoff/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({ user: userId }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to hand off task: ${response.statusText}`);
    }
    const data = (await response.json()) as Parameters<
      typeof normalizeTaskResponse
    >[0];
    return normalizeTaskResponse(data, { teamId });
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
        signal_report_task_relationship?: string;
        branch?: string | null;
        runtime_adapter?: string | null;
        model?: string | null;
        reasoning_effort?: string | null;
        channel?: string | null;
        pending_user_message?: string;
        pending_user_artifact_ids?: string[];
        auto_publish?: boolean;
        naming_source?: string;
      },
  ): Promise<Task> {
    const teamId = await this.getTeamId();
    const { origin_product: originProduct, ...taskOptions } = options;

    const data = await this.withCloudUsageLimitCheck(() =>
      this.api.post(`/api/projects/{project_id}/tasks/`, {
        path: { project_id: teamId.toString() },
        body: {
          ...taskOptions,
          origin_product: originProduct ?? "user_created",
        } as unknown as Schemas.Task,
      }),
    );

    return normalizeTaskResponse(data, { teamId });
  }

  async updateTask(
    taskId: string,
    updates: Partial<Schemas.Task>,
  ): Promise<Task> {
    const teamId = await this.getTeamId();
    const data = await this.api.patch(
      `/api/projects/{project_id}/tasks/{id}/`,
      {
        path: { project_id: teamId.toString(), id: taskId },
        body: updates,
      },
    );

    return normalizeTaskResponse(data, { teamId });
  }

  /**
   * Mirror this device's archive state onto the task, so every client agrees on
   * what is archived — and so the list endpoint, which hides archived tasks,
   * counts what the app actually shows. `archived` is on the write serializer
   * but not yet in the generated schema.
   */
  async setTaskArchived(taskId: string, archived: boolean): Promise<void> {
    await this.updateTask(taskId, {
      archived,
    } as unknown as Partial<Schemas.Task>);
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

  // All public channels plus the requester's #me. Creates nothing: startup provisions the
  // default spaces, which is what lets a caller gate on one already existing.
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

  // Resolve-or-create a public channel by name (idempotent server-side). `star`
  // only applies when this call creates the channel; an existing one keeps the
  // requester's star as it was.
  async resolveTaskChannel(
    name: string,
    options: { star: boolean },
  ): Promise<TaskChannel> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: {
        body: JSON.stringify({ name, star: options.star }),
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to resolve task channel: ${response.statusText}`);
    }
    return (await response.json()) as TaskChannel;
  }

  async renameTaskChannel(id: string, name: string): Promise<TaskChannel> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(id)}/`;
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({ name }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to rename task channel: ${response.statusText}`);
    }
    return (await response.json()) as TaskChannel;
  }

  async provisionDefaultTaskChannels(): Promise<ProvisionedTaskChannels> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/provision_defaults/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to provision default spaces: ${response.statusText}`,
      );
    }
    return (await response.json()) as ProvisionedTaskChannels;
  }

  /**
   * Opens the first-run agent session in #general. Reads the company's homepage, so it takes a
   * few seconds; callers fire it without awaiting. Resolves false when no session was started,
   * which is the normal path while the spaces rollout has not reached this user.
   */
  async startOnboardingSession(): Promise<string | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/onboarding_session/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) return null;
    const data = (await response.json()) as { task_id?: string | null };
    return data.task_id ?? null;
  }

  async startOnboardingTestSession(input: {
    company_domain: string;
    joining_existing_organization: boolean;
    has_events: boolean;
    signal_reports_waiting: number;
    other_members: string[];
    sources_enabled: string[];
    sources_watching: string[];
    sources_newly_enabled: boolean;
  }): Promise<{ task_id: string; channel_id: string }> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/onboarding_session_test/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify(input) },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to start test onboarding session: ${response.statusText}`,
      );
    }
    return (await response.json()) as { task_id: string; channel_id: string };
  }

  async createTeachingCanvasForTest(): Promise<{
    canvas_id: string;
    channel_id: string;
  }> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/teaching_canvas_test/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(
        `Failed to create teaching canvas: ${response.statusText}`,
      );
    }
    return (await response.json()) as { canvas_id: string; channel_id: string };
  }

  async updateTaskChannelRepositories(
    id: string,
    githubIntegration: number | null,
    repositories: string[],
  ): Promise<TaskChannel> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(id)}/`;
    const response = await this.api.fetcher.fetch({
      method: "patch",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: {
        body: JSON.stringify({
          github_integration: githubIntegration,
          repositories,
        }),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to update space repositories: ${response.statusText}`,
      );
    }
    return (await response.json()) as TaskChannel;
  }

  async deleteTaskChannel(id: string): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(id)}/`;
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(`Failed to delete task channel: ${response.statusText}`);
    }
  }

  async starTaskChannel(id: string, starred: boolean): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(id)}/star/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: { body: JSON.stringify({ starred }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to star task channel: ${response.statusText}`);
    }
  }

  async getChannelInstructions(
    channelId: string,
  ): Promise<ChannelInstructions | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(channelId)}/instructions/`;
    const response = await this.api.fetcher.fetch({
      method: "get",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (response.status === 404) return null;
    if (!response.ok) {
      throw new Error(
        `Failed to fetch channel instructions: ${response.statusText}`,
      );
    }
    return (await response.json()) as ChannelInstructions;
  }

  async putChannelInstructions(
    channelId: string,
    input: { content: string; baseVersion?: number },
  ): Promise<ChannelInstructions> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(channelId)}/instructions/`;
    const response = await this.api.fetcher.fetch({
      method: "put",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: {
        body: JSON.stringify({
          content: input.content,
          ...(input.baseVersion !== undefined
            ? { base_version: input.baseVersion }
            : {}),
        }),
      },
    });
    if (response.status === 409) {
      throw new FolderInstructionsConflictError();
    }
    if (!response.ok) {
      throw new Error(
        `Failed to publish channel instructions: ${response.statusText}`,
      );
    }
    return (await response.json()) as ChannelInstructions;
  }

  async deleteChannelInstructions(channelId: string): Promise<void> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(channelId)}/instructions/`;
    const response = await this.api.fetcher.fetch({
      method: "delete",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
    });
    if (!response.ok && response.status !== 404) {
      throw new Error(
        `Failed to delete channel instructions: ${response.statusText}`,
      );
    }
  }

  async listChannelInstructionVersions(
    channelId: string,
  ): Promise<ChannelInstructionsVersion[]> {
    const maxPages = 20;
    const teamId = await this.getTeamId();
    const all: ChannelInstructionsVersion[] = [];
    let urlPath = `/api/projects/${teamId}/task_channels/${encodeURIComponent(channelId)}/instructions/versions/`;
    for (let i = 0; i < maxPages; i++) {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url: new URL(`${this.api.baseUrl}${urlPath}`),
        path: urlPath,
      });
      if (!response.ok) {
        throw new Error(
          `Failed to fetch channel instruction versions: ${response.statusText}`,
        );
      }
      const body = (await response.json()) as
        | ChannelInstructionsVersion[]
        | { next: string | null; results: ChannelInstructionsVersion[] };
      if (Array.isArray(body)) return [...all, ...body];
      all.push(...body.results);
      if (!body.next) return all;
      const nextUrl = new URL(body.next);
      urlPath = `${nextUrl.pathname}${nextUrl.search}`;
    }
    log.warn("Channel instruction version pagination limit reached", {
      channelId,
      returned: all.length,
    });
    return all;
  }

  // ---- Organization context wiki (context_layer) ------------------------
  // Org-scoped: the wiki is one repo per organization, shared across projects.
  // 404 means the wiki was never enabled; 403 means it exists but is dark
  // because the organization has private projects.

  // GET with the wiki's shared read semantics: 404 (never enabled or missing
  // page) reads as null, 403 (privacy guard) as ContextWikiUnavailableError.
  private async getContextWikiResource<T>(urlPath: string): Promise<T | null> {
    try {
      const response = await this.api.fetcher.fetch({
        method: "get",
        url: new URL(`${this.api.baseUrl}${urlPath}`),
        path: urlPath,
      });
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ApiRequestError) {
        if (error.status === 404) return null;
        if (error.status === 403) {
          throw new ContextWikiUnavailableError(readDetail(error));
        }
      }
      throw error;
    }
  }

  async getContextWikiTree(): Promise<ContextWikiTree | null> {
    return this.getContextWikiResource<ContextWikiTree>(
      `/api/organizations/@current/context_layer/tree/`,
    );
  }

  async getContextWikiPage(path: string): Promise<ContextWikiPage | null> {
    return this.getContextWikiResource<ContextWikiPage>(
      `/api/organizations/@current/context_layer/pages/?path=${encodeURIComponent(path)}`,
    );
  }

  async getContextWikiHealthReport(): Promise<ContextWikiHealthReport | null> {
    return this.getContextWikiResource<ContextWikiHealthReport>(
      `/api/organizations/@current/context_layer/wiki/report/`,
    );
  }

  async getChannelContextWikiPage(
    channelId: string,
  ): Promise<ChannelContextWikiPage | null> {
    return this.getContextWikiResource<ChannelContextWikiPage>(
      `/api/organizations/@current/context_layer/channel-pages/${encodeURIComponent(channelId)}/`,
    );
  }

  /**
   * Full-content page write guarded by `baseHead` optimistic concurrency.
   * The server holds a per-org writer lock shared with agent commit landings;
   * a lock-busy 429 surfaces as ApiRequestError and is safe to retry with the
   * same base head — callers configure that retry (see
   * `useContextWikiPageMutation`). 409 (stale base head) and 400 (lint) are
   * the actionable failures.
   */
  async putContextWikiPage(input: {
    path: string;
    content: string;
    baseHead: string;
  }): Promise<{ head_sha: string }> {
    const urlPath = `/api/organizations/@current/context_layer/pages/`;
    try {
      const response = await this.api.fetcher.fetch({
        method: "put",
        url: new URL(`${this.api.baseUrl}${urlPath}`),
        path: urlPath,
        overrides: {
          body: JSON.stringify({
            path: input.path,
            content: input.content,
            base_head: input.baseHead,
          }),
        },
      });
      return (await response.json()) as { head_sha: string };
    } catch (error) {
      if (!(error instanceof ApiRequestError)) throw error;
      if (error.status === 409) {
        const body = error.body as { current_head?: string } | null;
        throw new ContextWikiConflictError(body?.current_head ?? null);
      }
      if (error.status === 400) {
        const body = error.body as {
          detail?: string;
          errors?: string[];
        } | null;
        throw new ContextWikiLintError(
          body?.detail ?? "The change violates the wiki structure.",
          body?.errors ?? [],
        );
      }
      if (error.status === 403) {
        throw new ContextWikiUnavailableError(readDetail(error));
      }
      throw error;
    }
  }

  async enableContextWiki(): Promise<{ head_sha: string }> {
    const urlPath = `/api/organizations/@current/context_layer/enable/`;
    try {
      const response = await this.api.fetcher.fetch({
        method: "post",
        url: new URL(`${this.api.baseUrl}${urlPath}`),
        path: urlPath,
        overrides: { body: JSON.stringify({}) },
      });
      return (await response.json()) as { head_sha: string };
    } catch (error) {
      if (error instanceof ApiRequestError) {
        throw new Error(
          `Failed to enable the context wiki: ${readDetail(error)}`,
        );
      }
      throw error;
    }
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

  // Task lifecycle and individual comment activity, newest first.
  async getTaskActivity(options?: {
    before?: string;
    beforeId?: string;
  }): Promise<TaskActivityPage> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_activity/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    if (options?.before && options.beforeId) {
      url.searchParams.set("before", options.before);
      url.searchParams.set("before_id", options.beforeId);
    }
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: urlPath,
    });
    if (!response.ok) {
      throw new Error(`Failed to fetch task activity: ${response.statusText}`);
    }
    return (await response.json()) as TaskActivityPage;
  }

  // Task lifecycle activity clears by task timestamp; comment activity clears by row id.
  async markTaskActivityRead(
    activities: TaskActivityReadMarker[],
  ): Promise<TaskActivityMarkReadResult> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/task_activity/mark_read/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${urlPath}`),
      path: urlPath,
      overrides: {
        body: JSON.stringify({ activities }),
      },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to mark task activity read: ${response.statusText}`,
      );
    }
    return (await response.json()) as TaskActivityMarkReadResult;
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
    method: CloudRunCommandMethod,
    params?: Record<string, unknown>,
  ): Promise<{ success: boolean; result?: unknown; error?: string }> {
    try {
      return {
        success: true,
        result: await this.sendCloudRunCommand(taskId, runId, method, params),
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async sendCloudRunCommand(
    taskId: string,
    runId: string,
    method: CloudRunCommandMethod,
    params: Record<string, unknown> = {},
  ): Promise<unknown> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/command/`,
    );
    const body = {
      jsonrpc: "2.0",
      method,
      params,
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

      const data = (await response.json()) as {
        error?: unknown;
        result?: unknown;
      };
      if (data.error) {
        const backendError = cloudCommandBackendError(data);
        throw new CloudCommandError(
          method,
          response.status,
          backendError,
          `Cloud command '${method}' error: ${backendError ?? JSON.stringify(data.error)}`,
        );
      }

      return data.result;
    } catch (error) {
      if (error instanceof CloudCommandError) throw error;
      if (error instanceof ApiRequestError) {
        this.throwIfCloudUsageLimit(error);
        const backendError = cloudCommandBackendError(error.body);
        throw new CloudCommandError(
          method,
          error.status,
          backendError,
          `Cloud command '${method}' failed: ${error.status}${backendError ? ` ${backendError}` : ""}`,
        );
      }
      throw error;
    }
  }

  async cancelTaskRun(
    taskId: string,
    runId: string,
    reason?: string,
  ): Promise<{ status?: string }> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/cancel/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${path}`),
      path,
      overrides: {
        body: JSON.stringify(reason ? { reason } : {}),
      },
    });
    return (await response.json().catch(() => ({}))) as { status?: string };
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

    return normalizeTaskResponse(data, { teamId });
  }

  async warmTask(options: {
    repository?: string | null;
    repositories?: string[];
    github_integration?: number | null;
    branch?: string | null;
    runtime_adapter?: string | null;
    model?: string | null;
    reasoning_effort?: string | null;
    context_window?: "200k" | "1m" | null;
    fast_mode?: boolean | null;
    sandbox_environment_id?: string | null;
    custom_image_id?: string | null;
  }): Promise<{ task_id: string; run_id: string } | null> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/tasks/warm/`;
    const url = new URL(`${this.api.baseUrl}${urlPath}`);
    const response = await this.withCloudUsageLimitCheck(() =>
      this.api.fetcher.fetch({
        method: "post",
        url,
        path: urlPath,
        overrides: {
          body: JSON.stringify({
            repository: options.repository,
            repositories: options.repositories,
            github_integration: options.github_integration,
            branch: options.branch ?? null,
            runtime_adapter: options.runtime_adapter ?? null,
            model: options.model ?? null,
            reasoning_effort: options.reasoning_effort ?? null,
            ...(options.context_window
              ? { context_window: options.context_window }
              : {}),
            ...(options.fast_mode != null
              ? { fast_mode: options.fast_mode }
              : {}),
            ...(options.sandbox_environment_id
              ? { sandbox_environment_id: options.sandbox_environment_id }
              : {}),
            ...(options.custom_image_id
              ? { custom_image_id: options.custom_image_id }
              : {}),
          }),
        },
      }),
    );
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

  async registerTaskRunPostHogReferences(
    taskId: string,
    runId: string,
    references: PostHogObjectReferenceInput[],
  ): Promise<TaskRunArtifact[]> {
    if (references.length === 0) return [];
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/references/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${path}`),
      path,
      overrides: { body: JSON.stringify({ references }) },
    });
    if (!response.ok) {
      throw new Error(`Failed to register references: ${response.statusText}`);
    }
    const data = (await response.json()) as {
      artifacts?: TaskRunArtifactDTO[];
    };
    return (data.artifacts ?? []).map(normalizeTaskRunArtifact);
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

  async getResourceComments(
    scope: CommentScope,
    itemId: string,
    taskId: string,
  ): Promise<ResourceComment[]> {
    const MAX_COMMENT_PAGES = 50;
    const teamId = await this.getTeamId();
    const comments: ResourceComment[] = [];
    let cursor: string | undefined;
    for (let pageIndex = 0; pageIndex < MAX_COMMENT_PAGES; pageIndex++) {
      const page = await this.api.get("/api/projects/{project_id}/comments/", {
        path: { project_id: String(teamId) },
        query: { scope, item_id: itemId, task_id: taskId, cursor },
      });
      comments.push(...page.results);
      cursor = page.next
        ? (new URL(page.next).searchParams.get("cursor") ?? undefined)
        : undefined;
      if (!cursor) return comments;
    }
    log.warn(
      `getResourceComments hit MAX_PAGES (${MAX_COMMENT_PAGES}); returning partial results`,
      { scope, itemId, returned: comments.length },
    );
    return comments;
  }

  async createResourceComment(
    request: CreateResourceCommentRequest,
  ): Promise<ResourceComment> {
    const teamId = await this.getTeamId();
    const payload = {
      content: request.content,
      scope: request.scope,
      item_id: request.itemId,
      item_context: request.context,
      source_comment: request.sourceCommentId ?? null,
      mentions: request.mentions ?? [],
      // Resolution is represented by a thread-state reply so this stays on the
      // same PAT-compatible write path as ordinary comments.
      is_task: false,
    };
    return await this.api.post("/api/projects/{project_id}/comments/", {
      path: { project_id: String(teamId) },
      body: payload as unknown as Schemas.Comment,
    });
  }

  /** Hide or restore every version of a file on the run, returning the updated manifest. */
  async setTaskRunArtifactsDismissed(
    taskId: string,
    runId: string,
    artifactIds: string[],
    dismissed: boolean,
  ): Promise<TaskRunArtifact[]> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/artifacts/dismiss/`;
    const response = await this.api.fetcher.fetch({
      method: "post",
      url: new URL(`${this.api.baseUrl}${path}`),
      path,
      overrides: {
        body: JSON.stringify({ artifact_ids: artifactIds, dismissed }),
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to update artifact: ${response.statusText}`);
    }

    const data = (await response.json()) as {
      artifacts?: TaskRunArtifactDTO[];
    };
    return (data.artifacts ?? []).map(normalizeTaskRunArtifact);
  }

  async getTaskSessionStorageAccess(
    taskId: string,
    runId: string,
  ): Promise<TaskSessionStorageAccess | null> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/task_session/`,
    );
    const response = await this.api.fetcher.fetch({
      method: "get",
      url,
      path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/task_session/`,
    });
    if (response.status === 404) {
      return null;
    }
    if (!response.ok) {
      throw new Error(`Failed to load task session: ${response.statusText}`);
    }

    return (await response.json()) as TaskSessionStorageAccess;
  }

  async resumeRunInCloud(taskId: string, runId: string): Promise<TaskRun> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/resume_in_cloud/`,
    );
    const response = await this.withCloudUsageLimitCheck(() =>
      this.api.fetcher.fetch({
        method: "post",
        url,
        path: `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/resume_in_cloud/`,
      }),
    );

    if (!response.ok) {
      throw new Error(`Failed to resume run in cloud: ${response.statusText}`);
    }

    const data = (await response.json()) as Schemas.TaskRunDetail;
    return normalizeTaskRunResponse(data, { teamId, taskId });
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

    const data =
      (await response.json()) as Partial<Schemas.PaginatedTaskRunDetailList>;
    return (data.results ?? []).map((run) =>
      normalizeTaskRunResponse(run, { teamId, taskId }),
    );
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

    const data = (await response.json()) as Schemas.TaskRunDetail;
    return normalizeTaskRunResponse(data, { teamId, taskId });
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

    const data = (await response.json()) as Schemas.TaskRunDetail;
    return normalizeTaskRunResponse(data, { teamId, taskId });
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

    const data = (await response.json()) as Schemas.Task;
    return normalizeTaskResponse(data, { teamId });
  }

  async updateTaskRun(
    taskId: string,
    runId: string,
    updates: Partial<
      Pick<
        TaskRun,
        "status" | "branch" | "stage" | "error_message" | "output" | "state"
      >
    > & {
      state_append?: Record<string, unknown>;
    },
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
    return normalizeTaskRunResponse(data, { teamId, taskId });
  }

  async analyzeTaskRun(
    taskId: string,
    runId: string,
  ): Promise<{ analysis_task_id: string; created: boolean }> {
    const teamId = await this.getTeamId();
    const data = await this.api.post(
      //@ts-expect-error this is not in the generated client
      `/api/projects/{project_id}/tasks/{task_id}/runs/{id}/analyze/`,
      {
        path: {
          project_id: teamId.toString(),
          task_id: taskId,
          id: runId,
        },
      },
    );
    return data as { analysis_task_id: string; created: boolean };
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

  /**
   * Record a `/clear` boundary in a finished run's log, so the next run in the
   * chain resumes past it with an empty conversation. Only valid for a finished
   * run, because an active one has an agent that owns the clear (409 otherwise).
   */
  async clearTaskRunConversation(taskId: string, runId: string): Promise<void> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/clear_conversation/`;
    const url = new URL(`${this.api.baseUrl}${path}`);

    // The shared fetcher throws `Failed request: [<status>] <json-body>` for any non-2xx, so
    // unwrap that into the endpoint's clean `error` message rather than surfacing the raw string.
    try {
      await this.api.fetcher.fetch({ method: "post", url, path });
    } catch (error) {
      throw new Error(
        extractRequestErrorMessage(error, "Couldn’t clear the conversation."),
      );
    }
  }

  // AbortController + setTimeout because Hermes, which runs this client on
  // mobile, has no AbortSignal.timeout.
  private async fetchSessionLogsPage(
    url: URL,
    path: string,
    offset: number,
  ): Promise<SessionLogsPage> {
    for (let attempt = 0; ; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(
        () =>
          controller.abort(new Error("Session logs page request timed out")),
        SESSION_LOGS_PAGE_TIMEOUT_MS,
      );
      try {
        const response = await this.api.fetcher.fetch({
          method: "get",
          url,
          path,
          overrides: { signal: controller.signal },
        });
        if (!response.ok) {
          return {
            ok: false,
            status: response.status,
            statusText: response.statusText,
          };
        }
        // Read the body here, while the timer is still armed: fetch resolves on
        // headers, and a page body stalling after them is what wedges hydration.
        const entries = (await response.json()) as StoredLogEntry[];
        return { ok: true, entries, headers: response.headers };
      } catch (err) {
        const status = requestErrorStatus(err);
        const retryable = status === undefined || status >= 500;
        if (attempt > 0 || !retryable) throw err;
        log.warn(`Retrying session logs page at offset ${offset}`, err);
      } finally {
        clearTimeout(timer);
      }
    }
  }

  async getTaskRunSessionLogsPage(
    taskId: string,
    runId: string,
    options: { limit: number; offset?: number; after?: string },
  ): Promise<TaskRunSessionLogsPage> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/tasks/${taskId}/runs/${runId}/session_logs/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    url.searchParams.set("limit", String(options.limit));
    if (options.offset) {
      url.searchParams.set("offset", String(options.offset));
    }
    if (options.after) {
      url.searchParams.set("after", options.after);
    }
    const page = await this.fetchSessionLogsPage(
      url,
      path,
      options.offset ?? 0,
    );
    if (!page.ok) {
      throw new Error(
        `Failed to fetch session logs page at offset ${options.offset ?? 0}: ${page.status} ${page.statusText}`,
      );
    }
    // Number(null) is 0, so an absent header must stay null.
    const matchingHeader = page.headers.get("X-Matching-Count");
    const matchingCount =
      matchingHeader === null ? null : Number(matchingHeader);
    return {
      entries: page.entries,
      hasMore: page.headers.get("X-Has-More") === "true",
      matchingCount:
        matchingCount !== null && Number.isFinite(matchingCount)
          ? matchingCount
          : null,
    };
  }

  async getTaskRunSessionLogsResult(
    taskId: string,
    runId: string,
    options?: { limit?: number; after?: string },
  ): Promise<TaskRunSessionLogsResult> {
    const maxEntries = options?.limit ?? SESSION_LOGS_MAX_PAGE_SIZE;
    const entries: StoredLogEntry[] = [];
    let truncatedHeadCount = 0;
    try {
      let offset = 0;
      let isFirstPage = true;
      while (entries.length < maxEntries) {
        const page = await this.getTaskRunSessionLogsPage(taskId, runId, {
          limit: Math.min(
            SESSION_LOGS_MAX_PAGE_SIZE,
            maxEntries - entries.length,
          ),
          offset,
          after: options?.after,
        });
        if (isFirstPage) {
          isFirstPage = false;
          if (page.matchingCount !== null && page.matchingCount > maxEntries) {
            // Restart from the tail so the newest maxEntries survive the cap.
            truncatedHeadCount = page.matchingCount - maxEntries;
            offset = truncatedHeadCount;
            continue;
          }
        }
        entries.push(...page.entries);
        if (!page.hasMore || page.entries.length === 0) {
          return { entries, complete: true, truncatedHeadCount };
        }
        offset += page.entries.length;
      }
      // A deliberate tail fetch is complete; capping out without a matching
      // count means unknown loss.
      return { entries, complete: truncatedHeadCount > 0, truncatedHeadCount };
    } catch (err) {
      log.warn("Failed to fetch task run session logs", err);
      return { entries, complete: false, truncatedHeadCount };
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
    total: number | null;
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

    const data = (await response.json()) as {
      has_more?: boolean;
      total?: number;
    };
    return {
      repositories: this.normalizeGithubRepositories(data),
      hasMore: data.has_more ?? false,
      total: typeof data.total === "number" ? data.total : null,
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
    total: number | null;
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

    const data = (await response.json()) as {
      has_more?: boolean;
      total?: number;
    };
    return {
      repositories: this.normalizeGithubRepositories(data),
      hasMore: data.has_more ?? false,
      total: typeof data.total === "number" ? data.total : null,
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
    if (params?.channel_id) {
      url.searchParams.set("channel_id", params.channel_id);
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
   * Refund a report's billed PR. The server freezes the billing path, archives
   * the report, and kicks off the billing credit when one is due; it also
   * enforces eligibility, so callers only gate for display.
   */
  async refundSignalReport(
    reportId: string,
    input: { reason: SignalReportRefundReason; note?: string },
  ): Promise<SignalReport> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/signals/reports/${reportId}/refund/`;
    const url = new URL(`${this.api.baseUrl}${path}`);

    // The shared fetcher throws `Failed request: [<status>] <json-body>` for any non-2xx, so
    // unwrap that into the endpoint's clean `error` message (e.g. the eligibility failures)
    // rather than surfacing the raw string.
    let response: Response;
    try {
      response = await this.api.fetcher.fetch({
        method: "post",
        url,
        path,
        overrides: {
          body: JSON.stringify(input),
        },
      });
    } catch (error) {
      throw new Error(
        extractRequestErrorMessage(error, "Failed to refund this report's PR"),
      );
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
      max_reports_per_day: number | null;
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

  async installCustomMcpServer(
    options: {
      name: string;
      url: string;
      auth_type: McpAuthType;
      api_key?: string;
      description?: string;
      client_id?: string;
      client_secret?: string;
      install_source?: "posthog" | "posthog-code";
      posthog_code_callback_url?: string;
    } & McpGatewayInstallSharingOptions,
  ): Promise<McpServerInstallation | Schemas.OAuthRedirectResponse> {
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

  async installMcpTemplate(
    options: {
      template_id: string;
      api_key?: string;
      install_source?: "posthog" | "posthog-code";
      posthog_code_callback_url?: string;
    } & McpGatewayInstallSharingOptions,
  ): Promise<McpServerInstallation | Schemas.OAuthRedirectResponse> {
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

  // ---- MCP gateway (team control plane, behind the `mcp-gateway` flag) ----

  /**
   * JSON request against the team-scoped MCP gateway API. `path` is relative
   * to `/api/projects/{teamId}/` and must keep its trailing slash.
   */
  private async mcpGatewayFetch<T>(args: {
    method: "get" | "post" | "patch" | "delete";
    path: string;
    search?: Record<string, string | number | undefined>;
    body?: unknown;
    errorLabel: string;
  }): Promise<T> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/${args.path}`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    for (const [key, value] of Object.entries(args.search ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
    const response = await this.api.fetcher.fetch({
      method: args.method,
      url,
      path,
      ...(args.body !== undefined
        ? { overrides: { body: JSON.stringify(args.body) } }
        : {}),
    });
    if (!response.ok && response.status !== 204) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        (errorData as { detail?: string }).detail ??
          `${args.errorLabel}: ${response.statusText}`,
      );
    }
    if (response.status === 204) return undefined as T;
    return (await response.json().catch(() => undefined)) as T;
  }

  async getMcpGatewayConfig(): Promise<TeamMcpGatewayConfig> {
    return this.mcpGatewayFetch({
      method: "get",
      path: "mcp_gateway/config/",
      errorLabel: "Failed to fetch gateway settings",
    });
  }

  async updateMcpGatewaySettings(
    update: TeamMcpGatewayConfigUpdate,
  ): Promise<TeamMcpGatewayConfig> {
    return this.mcpGatewayFetch({
      method: "post",
      path: "mcp_gateway/config/update_settings/",
      body: update,
      errorLabel: "Failed to update gateway settings",
    });
  }

  /**
   * Admin: set the team posture for untouched catalog servers and bulk-apply
   * the same state to every existing gateway row.
   */
  async setAllMcpGatewayServersEnabled(
    enabled: boolean,
  ): Promise<TeamMcpGatewayConfig> {
    return this.mcpGatewayFetch({
      method: "post",
      path: "mcp_gateway/config/set_all_servers_enabled/",
      body: { enabled },
      errorLabel: "Failed to update servers",
    });
  }

  async getMcpGatewayServers(): Promise<McpGatewayServer[]> {
    const data = await this.mcpGatewayFetch<{ results?: McpGatewayServer[] }>({
      method: "get",
      path: "mcp_gateway/servers/",
      search: { limit: 500 },
      errorLabel: "Failed to fetch gateway servers",
    });
    return data.results ?? [];
  }

  async getMcpGatewayServer(serverId: string): Promise<McpGatewayServer> {
    return this.mcpGatewayFetch({
      method: "get",
      path: `mcp_gateway/servers/${serverId}/`,
      errorLabel: "Failed to fetch gateway server",
    });
  }

  async updateMcpGatewayServer(
    serverId: string,
    updates: McpGatewayServerUpdate,
  ): Promise<McpGatewayServer> {
    return this.mcpGatewayFetch({
      method: "patch",
      path: `mcp_gateway/servers/${serverId}/`,
      body: updates,
      errorLabel: "Failed to update gateway server",
    });
  }

  /**
   * Admin: enable or disable a catalog template the team never touched,
   * materializing a gateway row for it (or updating the existing one).
   */
  async setMcpGatewayTemplateEnabled(options: {
    templateId: string;
    enabled: boolean;
  }): Promise<McpGatewayServer> {
    return this.mcpGatewayFetch({
      method: "post",
      path: "mcp_gateway/servers/set_template_enabled/",
      body: { template_id: options.templateId, enabled: options.enabled },
      errorLabel: "Failed to update catalog server",
    });
  }

  /**
   * Disconnect every member and delete the row. The registry is sparse, so a
   * deleted catalog server simply follows the team default again.
   */
  async deleteMcpGatewayServer(serverId: string): Promise<void> {
    await this.mcpGatewayFetch<void>({
      method: "delete",
      path: `mcp_gateway/servers/${serverId}/`,
      errorLabel: "Failed to remove gateway server",
    });
  }

  /** Tool catalog with the effective policy resolved for one scope. */
  async getMcpGatewayToolPolicies(
    serverId: string,
    scope: McpGatewayPolicyScope = {},
  ): Promise<McpResolvedToolPolicy[]> {
    const data = await this.mcpGatewayFetch<{
      results?: McpResolvedToolPolicy[];
    }>({
      method: "get",
      path: `mcp_gateway/servers/${serverId}/tools/`,
      search: {
        scope_type: scope.scope_type,
        scope_user_id: scope.scope_user_id,
        scope_service_account_id: scope.scope_service_account_id,
      },
      errorLabel: "Failed to fetch tool policies",
    });
    return data.results ?? [];
  }

  /** Upsert per-tool states for a scope; returns the re-resolved catalog. */
  async upsertMcpGatewayToolPolicies(
    serverId: string,
    options: McpGatewayPolicyScope & { policies: McpToolPolicyEntry[] },
  ): Promise<McpResolvedToolPolicy[]> {
    const data = await this.mcpGatewayFetch<{
      results?: McpResolvedToolPolicy[];
    }>({
      method: "post",
      path: `mcp_gateway/servers/${serverId}/policies/`,
      body: options,
      errorLabel: "Failed to update tool policies",
    });
    return data.results ?? [];
  }

  async getMcpServiceAccounts(): Promise<McpServiceAccount[]> {
    const data = await this.mcpGatewayFetch<{ results?: McpServiceAccount[] }>({
      method: "get",
      path: "mcp_gateway/service_accounts/",
      search: { limit: 500 },
      errorLabel: "Failed to fetch service accounts",
    });
    return data.results ?? [];
  }

  async getMcpServiceAccount(accountId: string): Promise<McpServiceAccount> {
    return this.mcpGatewayFetch({
      method: "get",
      path: `mcp_gateway/service_accounts/${accountId}/`,
      errorLabel: "Failed to fetch service account",
    });
  }

  /** Returns the full bearer token exactly once. */
  async createMcpServiceAccount(options: {
    name: string;
    description?: string;
  }): Promise<McpServiceAccountWithToken> {
    return this.mcpGatewayFetch({
      method: "post",
      path: "mcp_gateway/service_accounts/",
      body: options,
      errorLabel: "Failed to create service account",
    });
  }

  async updateMcpServiceAccount(
    accountId: string,
    updates: {
      name?: string;
      description?: string;
      status?: McpServiceAccountStatus;
    },
  ): Promise<McpServiceAccount> {
    return this.mcpGatewayFetch({
      method: "patch",
      path: `mcp_gateway/service_accounts/${accountId}/`,
      body: updates,
      errorLabel: "Failed to update service account",
    });
  }

  async deleteMcpServiceAccount(accountId: string): Promise<void> {
    await this.mcpGatewayFetch<void>({
      method: "delete",
      path: `mcp_gateway/service_accounts/${accountId}/`,
      errorLabel: "Failed to delete service account",
    });
  }

  /** Grant or revoke one agent's access to one gateway server. */
  async setMcpServiceAccountAccess(
    accountId: string,
    options: {
      gateway_server_id: string;
      enabled: boolean;
      /**
       * Reach of the caller's own share. The server defaults an omitted
       * scope to "personal", so re-enabling without it resets a team share.
       */
      scope?: McpAgentGrantScope;
      /** Agent-scope tool policies to set alongside the grant. */
      policies?: McpToolPolicyEntry[];
    },
  ): Promise<McpServiceAccount> {
    return this.mcpGatewayFetch({
      method: "post",
      path: `mcp_gateway/service_accounts/${accountId}/access/`,
      body: options,
      errorLabel: "Failed to update agent access",
    });
  }

  async getMcpGatewayMembers(): Promise<McpGatewayMemberSummary[]> {
    const data = await this.mcpGatewayFetch<{
      results?: McpGatewayMemberSummary[];
    }>({
      method: "get",
      path: "mcp_gateway/members/",
      search: { limit: 500 },
      errorLabel: "Failed to fetch gateway members",
    });
    return data.results ?? [];
  }

  /** Turn one gateway server off (or back on) for one member. */
  async setMcpGatewayMemberAccess(
    userId: number,
    options: { gateway_server_id: string; enabled: boolean },
  ): Promise<void> {
    await this.mcpGatewayFetch<void>({
      method: "post",
      path: `mcp_gateway/members/${userId}/set_access/`,
      body: options,
      errorLabel: "Failed to update member access",
    });
  }

  async getMcpGatewayAuditEvents(
    options: {
      quickFilter?: McpAuditQuickFilter;
      actorServiceAccountId?: string;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<McpAuditPage> {
    const data = await this.mcpGatewayFetch<{
      count?: number;
      results?: McpAuditEvent[];
    }>({
      method: "get",
      path: "mcp_gateway/audit/",
      search: {
        quick_filter: options.quickFilter,
        actor_service_account_id: options.actorServiceAccountId,
        limit: options.limit,
        offset: options.offset,
      },
      errorLabel: "Failed to fetch audit log",
    });
    return { count: data.count ?? 0, results: data.results ?? [] };
  }

  async getMcpGatewayAuditCounts(): Promise<McpAuditCounts> {
    return this.mcpGatewayFetch({
      method: "get",
      path: "mcp_gateway/audit/counts/",
      errorLabel: "Failed to fetch audit counts",
    });
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
      this.throwIfCloudUsageLimit(error);
      throw error;
    }
  }

  private throwIfCloudUsageLimit(error: unknown): void {
    const parsed = this.parseFetcherError(error);
    if (
      parsed &&
      parsed.status === 429 &&
      (parsed.body.code === "usage_limit_exceeded" ||
        parsed.body.code === DESKTOP_BILLING_LIMIT_ERROR_CODE)
    ) {
      const limitType = parsed.body.limit_type;
      throw new CloudUsageLimitError({
        limitType:
          limitType === "burst" || limitType === "sustained" ? limitType : null,
        resetAt:
          typeof parsed.body.reset_at === "string"
            ? parsed.body.reset_at
            : null,
        isPro: parsed.body.is_pro === true,
      });
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
    try {
      const response = await this.api.fetcher.fetch({
        method: "post",
        url,
        path: `/api/projects/${teamId}/sandbox_environments/`,
        overrides: {
          body: JSON.stringify(input),
        },
      });
      return (await response.json()) as SandboxEnvironment;
    } catch (error) {
      if (!(error instanceof ApiRequestError)) throw error;
      throw new Error(
        `Failed to create sandbox environment: ${readFieldErrors(error)}`,
      );
    }
  }

  async updateSandboxEnvironment(
    id: string,
    input: Partial<SandboxEnvironmentInput>,
  ): Promise<SandboxEnvironment> {
    const teamId = await this.getTeamId();
    const url = new URL(
      `${this.api.baseUrl}/api/projects/${teamId}/sandbox_environments/${id}/`,
    );
    try {
      const response = await this.api.fetcher.fetch({
        method: "patch",
        url,
        path: `/api/projects/${teamId}/sandbox_environments/${id}/`,
        overrides: {
          body: JSON.stringify(input),
        },
      });
      return (await response.json()) as SandboxEnvironment;
    } catch (error) {
      if (!(error instanceof ApiRequestError)) throw error;
      throw new Error(
        `Failed to update sandbox environment: ${readFieldErrors(error)}`,
      );
    }
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
   * The signed-in person's own spend limit, as the gateway holds it. A
   * deployment without the gateway wired answers `available: false` rather than
   * failing, so the settings page can say the limit informs only.
   */
  async getUserSpendLimit(): Promise<UserSpendLimit> {
    return parseUserSpendLimit(await this.spendLimitRequest("get"));
  }

  /** Sets the limit; `windowSeconds` is the window it resets over. */
  async setUserSpendLimit(
    limitUsd: number,
    windowSeconds: number,
  ): Promise<UserSpendLimit> {
    return parseUserSpendLimit(
      await this.spendLimitRequest("post", "", {
        limit_usd: String(limitUsd),
        window_seconds: windowSeconds,
      }),
    );
  }

  /** Removes the limit, so nothing holds this person's spend. */
  async clearUserSpendLimit(): Promise<UserSpendLimit> {
    return parseUserSpendLimit(
      await this.spendLimitRequest("delete", "clear/"),
    );
  }

  private async spendLimitRequest(
    method: "get" | "post" | "delete",
    suffix = "",
    body?: Record<string, unknown>,
  ): Promise<unknown> {
    const teamId = await this.getTeamId();
    const urlPath = `/api/projects/${teamId}/ai_gateway/@me/spend_limit/${suffix}`;
    // The shared fetcher throws `Failed request: [<status>] <json-body>` for any
    // non-2xx, so unwrap that into the endpoint's clean message rather than
    // surfacing the raw string in the settings toast.
    try {
      const response = await this.api.fetcher.fetch({
        method,
        url: new URL(`${this.api.baseUrl}${urlPath}`),
        path: urlPath,
        ...(body ? { overrides: { body: JSON.stringify(body) } } : {}),
      });
      return await response.json();
    } catch (error) {
      throw new Error(
        extractRequestErrorMessage(error, "Couldn't update your spend limit."),
      );
    }
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
    metadata?: Record<string, unknown>;
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
      metadata?: Record<string, unknown>;
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

  async runQuery(
    query: Record<string, unknown>,
    options?: { refresh?: "blocking" | false },
  ): Promise<Record<string, unknown>> {
    const teamId = await this.getTeamId();
    const path = `/api/projects/${teamId}/query/`;
    const url = new URL(`${this.api.baseUrl}${path}`);
    const refresh = options?.refresh === false ? null : "blocking";
    const response = await this.api.fetcher.fetch({
      method: "post",
      url,
      path,
      overrides: {
        body: JSON.stringify({ query, ...(refresh ? { refresh } : {}) }),
      },
    });
    const data = (await response.json()) as Record<string, unknown>;
    if (typeof data.error === "string" && data.error) {
      throw new Error(data.error);
    }
    return data;
  }

  /**
   * The insight's identity and query node, by short id. Backs saved-insight
   * chart cards in agent messages: the caller plans and runs the query.
   */
  async getInsightDefinition(shortId: string): Promise<{
    name: string | null;
    description: string | null;
    query: unknown;
    response: Record<string, unknown> | null;
  } | null> {
    const projectId = (await this.getTeamId()).toString();
    try {
      const insight = await this.api.get(
        "/api/projects/{project_id}/insights/{id}/",
        {
          path: { project_id: projectId, id: shortId },
          query: { refresh: "blocking" },
        },
      );
      return {
        name: insight.name || insight.derived_name || null,
        description: insight.description || null,
        query: insight.query ?? null,
        response:
          insight.result === null || insight.result === undefined
            ? null
            : {
                results: insight.result,
                columns: insight.columns ?? [],
              },
      };
    } catch (error) {
      if (requestErrorStatus(error) === 404) return null;
      throw error;
    }
  }

  /**
   * Resolves an `evidence:<kind>/<id>` citation from an agent message to a
   * small live summary of the object it points at. Returns null for kinds
   * without a lookup and for ids that don't resolve, so the caller can fall
   * back to a static reference. Query-backed kinds (hogql, insight) resolve
   * in the UI instead, where chart shaping lives.
   */
  async getEvidencePreview(
    kind: string,
    id: string,
  ): Promise<EvidencePreview | null> {
    const projectId = (await this.getTeamId()).toString();
    const numericId = /^\d+$/.test(id) ? Number(id) : null;

    switch (kind) {
      case "flag": {
        let flag: Schemas.FeatureFlag | undefined;
        if (numericId !== null) {
          flag = await this.api.get(
            "/api/projects/{project_id}/feature_flags/{id}/",
            { path: { project_id: projectId, id: numericId } },
          );
        } else {
          // Agents often cite flags by key; the API only retrieves by
          // numeric id, so find the exact key through the list search.
          const page = await this.api.get(
            "/api/projects/{project_id}/feature_flags/",
            { path: { project_id: projectId }, query: { search: id } },
          );
          flag = page.results.find((entry) => entry.key === id);
        }
        if (!flag) return null;
        // Depth: PostHog's own staleness verdict, and whether anything still
        // evaluates the flag (7-day call volume).
        const [status, volume] = await Promise.all([
          this.api
            .get("/api/projects/{project_id}/feature_flags/{id}/status/", {
              path: { project_id: projectId, id: flag.id },
            })
            .catch(() => null),
          this.runQuery({
            kind: "HogQLQuery",
            query: `SELECT toDate(timestamp) AS day, count() FROM events WHERE event = '$feature_flag_called' AND properties.$feature_flag = '${hogqlEscape(flag.key)}' AND timestamp >= now() - INTERVAL 7 DAY GROUP BY day ORDER BY day`,
          }).catch(() => ({})),
        ]);
        return decorateFlagPreview(
          shapeFlagPreview(flag),
          status,
          gridRows(volume),
        );
      }
      case "experiment": {
        if (numericId === null) return null;
        const experiment = await this.api.get(
          "/api/projects/{project_id}/experiments/{id}/",
          { path: { project_id: projectId, id: numericId } },
        );
        const preview = shapeExperimentPreview(experiment);
        const primaryQueries = experimentMetricQueries(experiment, "primary");
        const secondaryQueries = experimentMetricQueries(
          experiment,
          "secondary",
        );
        if (!experiment.start_date) {
          return {
            ...preview,
            experimentResults: shapeExperimentResults(experiment, null, [], []),
          };
        }

        const runMetricQuery = async (
          metric: unknown,
        ): Promise<ExperimentMetricQueryResult> => {
          if (!metric || typeof metric !== "object") {
            return { response: null };
          }
          try {
            const response = await this.runQuery(
              {
                kind: "ExperimentQuery",
                metric,
                experiment_id: numericId,
              },
              { refresh: false },
            );
            return {
              response: response as Schemas.ExperimentQueryResponse,
            };
          } catch {
            return { response: null };
          }
        };

        const exposureQuery = experiment.feature_flag
          ? this.runQuery(
              {
                kind: "ExperimentExposureQuery",
                experiment_id: numericId,
                experiment_name: experiment.name,
                exposure_criteria: experiment.exposure_criteria,
                feature_flag: experiment.feature_flag,
                start_date: experiment.start_date,
                end_date: experiment.end_date,
                holdout: experiment.holdout,
              },
              { refresh: false },
            ).catch(() => null)
          : Promise.resolve(null);
        const [exposureResponse, primaryResults, secondaryResults] =
          await Promise.all([
            exposureQuery,
            Promise.all(primaryQueries.map(runMetricQuery)),
            Promise.all(secondaryQueries.map(runMetricQuery)),
          ]);

        const experimentExposureResponse =
          exposureResponse as Schemas.ExperimentExposureQueryResponse | null;
        return {
          ...preview,
          experimentResults: shapeExperimentResults(
            experiment,
            experimentExposureResponse,
            primaryResults,
            secondaryResults,
          ),
          chart: shapeExperimentExposureChart(experimentExposureResponse),
        };
      }
      case "error": {
        // The issue's identity plus its 30-day activity: total events, users
        // affected, and a daily-occurrence spark answering "still firing?".
        const scope = `event = '$exception' AND properties.$exception_issue_id = '${hogqlEscape(id)}' AND timestamp >= now() - INTERVAL 30 DAY`;
        const [issue, totals, daily] = await Promise.all([
          this.api.get(
            "/api/environments/{project_id}/error_tracking/issues/{id}/",
            { path: { project_id: projectId, id } },
          ),
          this.runQuery({
            kind: "HogQLQuery",
            query: `SELECT count(), uniq(person_id) FROM events WHERE ${scope}`,
          }).catch(() => ({})),
          this.runQuery({
            kind: "HogQLQuery",
            query: `SELECT toDate(timestamp) AS day, count() FROM events WHERE ${scope} GROUP BY day ORDER BY day`,
          }).catch(() => ({})),
        ]);
        const preview = shapeErrorIssuePreview(issue);
        const totalRow = gridRows(totals)[0];
        const facts = [...(preview.facts ?? [])];
        const users = totalRow ? Number(totalRow[1]) : 0;
        const events = totalRow ? Number(totalRow[0]) : 0;
        if (Number.isFinite(users) && users > 0) {
          facts.unshift(
            `${compactCount(users)} users · ${compactCount(events)} events (30d)`,
          );
        }
        const stats = [
          ...(preview.stats ?? []),
          ...(users > 0
            ? [
                { label: "Users in 30 days", value: compactCount(users) },
                { label: "Events in 30 days", value: compactCount(events) },
              ]
            : []),
        ];
        const dailyRows = gridRows(daily);
        const points = dailySparkPoints(dailyRows);
        return {
          ...preview,
          facts,
          stats,
          spark:
            points.length > 1
              ? {
                  points,
                  labels: dailySparkLabels(dailyRows),
                  render: "bar" as const,
                }
              : undefined,
        };
      }
      case "event": {
        // Verify the event against its definition (also yields the id that
        // makes the reference clickable), then chart its 14-day volume.
        const definition = await this.api
          .get("/api/projects/{project_id}/event_definitions/by_name/", {
            path: { project_id: projectId },
            query: { name: id },
          })
          .catch(() => null);
        if (!definition) return null;
        const volume = await this.runQuery({
          kind: "HogQLQuery",
          query: `SELECT toDate(timestamp) AS day, count() FROM events WHERE event = '${hogqlEscape(id)}' AND timestamp >= now() - INTERVAL 14 DAY GROUP BY day ORDER BY day`,
        }).catch(() => ({}));
        const preview = shapeEventDefinitionPreview(definition);
        const volumeRows = gridRows(volume);
        const points = dailySparkPoints(volumeRows);
        const total = points.reduce((sum, value) => sum + value, 0);
        return {
          ...preview,
          facts:
            total > 0 ? [`${compactCount(total)} events (14d)`] : undefined,
          stats: [
            ...(total > 0
              ? [{ label: "Events in 14 days", value: compactCount(total) }]
              : []),
            ...(preview.stats ?? []),
          ],
          spark:
            points.length > 1
              ? {
                  points,
                  labels: dailySparkLabels(volumeRows),
                  render: "line" as const,
                }
              : undefined,
        };
      }
      case "ticket": {
        const ticket = await this.api.get(
          "/api/projects/{project_id}/conversations/tickets/{id}/",
          { path: { project_id: projectId, id } },
        );
        return shapeTicketPreview(ticket);
      }
      case "person": {
        if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(id)) {
          // A UUID-shaped id can be a person uuid or a UUID-shaped distinct id
          // (posthog-js writes anonymous distinct ids as UUIDs). Retrieve-by-id
          // matches only the person uuid, so a 404 (no such uuid) or 400 (the id
          // isn't a valid person uuid) means fall through and resolve it as a
          // distinct id below rather than giving up.
          const person = await this.api
            .get("/api/projects/{project_id}/persons/{id}/", {
              path: { project_id: projectId, id },
              query: {},
            })
            .catch((error) => {
              const status = requestErrorStatus(error);
              if (status === 404 || status === 400) return null;
              throw error;
            });
          if (person) return shapePersonPreview(person);
        }
        const page = await this.api.get("/api/projects/{project_id}/persons/", {
          path: { project_id: projectId },
          query: { search: id },
        });
        const person = page.results?.find(
          (candidate) =>
            candidate.uuid === id || candidate.distinct_ids?.includes(id),
        );
        return person ? shapePersonPreview(person) : null;
      }
      case "replay": {
        const recording = await this.api.get(
          "/api/projects/{project_id}/session_recordings/{id}/",
          { path: { project_id: projectId, id } },
        );
        return shapeRecordingPreview(recording);
      }
      case "survey": {
        const [survey, stats] = await Promise.all([
          this.api.get("/api/projects/{project_id}/surveys/{id}/", {
            path: { project_id: projectId, id },
          }),
          this.api
            .get("/api/projects/{project_id}/surveys/{id}/stats/", {
              path: { project_id: projectId, id },
              query: {},
            })
            .catch(() => null),
        ]);
        return decorateSurveyPreview(
          shapeSurveyPreview(survey),
          stats as Record<string, unknown> | null,
        );
      }
      case "trace": {
        const rollup = await this.runQuery({
          kind: "HogQLQuery",
          query: `SELECT count(), round(sum(toFloat(properties.$ai_total_cost_usd)), 3), round(sum(toFloat(properties.$ai_latency)), 1), groupUniqArray(properties.$ai_model), countIf(toString(properties.$ai_is_error) IN ('true', '1')) FROM events WHERE event IN ('$ai_generation', '$ai_embedding') AND properties.$ai_trace_id = '${hogqlEscape(id)}'`,
        });
        const row = gridRows(rollup)[0];
        return row ? shapeTracePreview(row) : null;
      }
      case "dashboard": {
        if (numericId === null) return null;
        const dashboard = await this.api.get(
          "/api/projects/{project_id}/dashboards/{id}/",
          { path: { project_id: projectId, id: numericId }, query: {} },
        );
        return shapeDashboardPreview(dashboard);
      }
      case "cohort": {
        if (numericId === null) return null;
        const cohort = await this.api.get(
          "/api/projects/{project_id}/cohorts/{id}/",
          { path: { project_id: projectId, id: numericId } },
        );
        return shapeCohortPreview(cohort);
      }
      case "action": {
        if (numericId === null) return null;
        const [action, volume, totals] = await Promise.all([
          this.api.get("/api/projects/{project_id}/actions/{id}/", {
            path: { project_id: projectId, id: numericId },
            query: {},
          }),
          this.runQuery({
            kind: "HogQLQuery",
            query: `SELECT toDate(timestamp) AS day, count() FROM events WHERE matchesAction(${numericId}) AND timestamp >= now() - INTERVAL 14 DAY GROUP BY day ORDER BY day`,
          }).catch(() => ({})),
          this.runQuery({
            kind: "HogQLQuery",
            query: `SELECT count(), uniq(person_id), max(timestamp) FROM events WHERE matchesAction(${numericId}) AND timestamp >= now() - INTERVAL 30 DAY`,
          }).catch(() => ({})),
        ]);
        const preview = shapeActionPreview(action);
        const volumeRows = gridRows(volume);
        const points = dailySparkPoints(volumeRows);
        const total = points.reduce((sum, value) => sum + value, 0);
        const facts = [...(preview.facts ?? [])];
        if (total > 0) facts.unshift(`${compactCount(total)} matches (14d)`);
        const totalsRow = gridRows(totals)[0];
        const matches30d = totalsRow ? Number(totalsRow[0]) : 0;
        const users30d = totalsRow ? Number(totalsRow[1]) : 0;
        const lastSeen =
          totalsRow && typeof totalsRow[2] === "string" && matches30d > 0
            ? totalsRow[2]
            : null;
        if (users30d > 0) facts.push(`${compactCount(users30d)} users (30d)`);
        return {
          ...preview,
          facts,
          stats: [
            ...(total > 0
              ? [{ label: "Matches in 14 days", value: compactCount(total) }]
              : []),
            ...(users30d > 0
              ? [{ label: "Users in 30 days", value: compactCount(users30d) }]
              : []),
            ...(lastSeen
              ? [{ label: "Last seen", value: formatDay(lastSeen) }]
              : []),
          ],
          spark:
            points.length > 1
              ? {
                  points,
                  labels: dailySparkLabels(volumeRows),
                  render: "line" as const,
                }
              : undefined,
          sections: [
            ...activitySection([
              [
                "Matches in 30 days",
                matches30d > 0 ? compactCount(matches30d) : null,
              ],
              [
                "Unique users in 30 days",
                users30d > 0 ? compactCount(users30d) : null,
              ],
              ["Last seen", lastSeen ? formatDay(lastSeen) : null],
            ]),
            ...(preview.sections ?? []),
          ],
        };
      }
      case "eval": {
        const evaluation = await this.api.get(
          "/api/environments/{project_id}/evaluations/{id}/",
          { path: { project_id: projectId, id } },
        );
        return shapeEvaluationPreview(evaluation);
      }
      default:
        return null;
    }
  }
}
