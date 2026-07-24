// biome-ignore-all lint/suspicious/noExplicitAny: SessionServiceDeps is the
// host seam for the ported renderer SessionService; the trpc/store/helper ports
// are satisfied by the desktop adapter and typed loosely at this boundary.
import type {
  ContentBlock,
  RequestPermissionRequest,
  SessionConfigOption,
  SessionConfigSelectGroup,
  SessionConfigSelectOption,
  SessionUpdate,
} from "@agentclientprotocol/sdk";
import {
  type AcpMessage,
  type Adapter,
  type AgentSession,
  type CloudRegion,
  classifyGatewayLimitError,
  type ExecutionMode,
  flattenSelectOptions,
  getBackoffDelay,
  getCloudUrlFromRegion,
  getConfigOptionByCategory,
  isFatalSessionError,
  isJsonRpcNotification,
  isJsonRpcRequest,
  isJsonRpcResponse,
  isPersistedOptionSupported,
  isRateLimitError,
  isTransientUpstreamError,
  mergeConfigOptions,
  type OptimisticItem,
  type PermissionRequest,
  type QueuedMessage,
  resolveBypassRevertMode,
  type StoredLogEntry,
  sendableQueuePrefixLength,
  sessionSupportsNativeSteer,
  type TaskRunArtifact,
  type TaskRunStatus,
} from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  type CloudTaskPermissionRequestUpdate,
  type CloudTaskUpdatePayload,
  type EffortLevel,
  effortLevelSchema,
  isTerminalStatus,
  type Task,
} from "@posthog/shared/domain-types";
import type { SpeechKind, SpeechSource } from "../speech/identifiers";
import {
  isNotification,
  POSTHOG_NOTIFICATIONS,
  SPEAK_TOOL_QUALIFIED_NAME,
} from "./acpNotifications";
import { createAppendOnlyTracker } from "./appendOnlyTracker";
import type {
  CloudArtifactClient,
  CloudSkillBundleRef,
} from "./cloudArtifactIdentifiers";
import { classifyCloudLogAppend } from "./cloudLogGap";
import { CloudLogGapReconciler } from "./cloudLogGapReconciler";
import { CloudRunIdleTracker } from "./cloudRunIdleTracker";
import {
  type CloudRuntimeOptions,
  getCloudPrAuthorshipMode,
  getCloudRunSource,
  getCloudRuntimeOptions,
} from "./cloudRunOptions";
import {
  addMissingCloudRuntimeConfigOptions,
  buildCloudDefaultConfigOptions,
  extractLatestConfigOptionsFromEntries,
} from "./cloudSessionConfig";
import {
  computeAutoRetryFinalState,
  OFFLINE_SESSION_MESSAGE,
  routeLocalConnect,
} from "./connectRouting";
import {
  formatPermissionAnswerPrompt,
  type PermissionSelectionPlan,
  planPermissionResponse,
} from "./permissionResponse";
import {
  convertStoredEntriesToEvents,
  createUserShellExecuteEvent,
  extractPromptText,
  getStoredLogEventPosition,
  getUserShellExecutesSinceLastPrompt,
  hasSessionPromptEvent,
  isTurnCompleteEvent,
  normalizePromptToBlocks,
  promptReferencesAbsoluteFolder,
  shellExecutesToContextBlocks,
} from "./sessionEvents";
import { selectSessionsToEvict } from "./sessionEviction";
import { createBaseSession } from "./sessionFactory";
import { type ParsedSessionLogs, parseSessionLogContent } from "./sessionLogs";

const LOCAL_SESSION_RECONNECT_ATTEMPTS = 3;
const LOCAL_SESSION_RECONNECT_BACKOFF = {
  initialDelayMs: 1_000,
  maxDelayMs: 5_000,
};
const LOCAL_SESSION_RECOVERY_MESSAGE =
  "Lost connection to the agent. Reconnecting…";
const LOCAL_SESSION_RECOVERY_FAILED_MESSAGE =
  "Connecting to to the agent has been lost. Retry, or start a new session.";
const GITHUB_AUTHORIZATION_REQUIRED_CODE = "github_authorization_required";
const AUTO_RETRY_MAX_ATTEMPTS = 2;
const AUTO_RETRY_DELAY_MS = 10_000;
const AUTH_RESTORE_MAX_RETRY_WAITS = 6;
const MAX_SUPERSEDED_RUN_IDS = 100;
const MAX_RESPONDED_PERMISSION_REQUEST_IDS = 500;
/**
 * Streamed events are buffered and flushed on this cadence so a burst of tokens
 * coalesces into one processing pass (and roughly one render) instead of one
 * per event. Electron IPC delivers each event as its own task, so a microtask
 * flush wouldn't batch across them — a short timer does. One frame is
 * imperceptible for streamed text.
 */
const SESSION_EVENT_FLUSH_MS = 16;
/**
 * A backgrounded session's transcript is freed this long after it stops being
 * viewed, and reloaded from disk on return. Only disconnected (idle, no live
 * subscription) sessions are eligible, so no streamed event can append to an
 * evicted transcript.
 */
const SESSION_EVENT_EVICT_GRACE_MS = 20_000;
/**
 * On open, paint the last this-many bytes of the log immediately so a big
 * transcript shows its latest turns in tens of ms, while the authoritative
 * full read + connect completes behind it. ~1.5MB is a few hundred entries —
 * plenty for the initial (scrolled-to-bottom) view.
 */
const OPEN_TAIL_BYTES = 1_500_000;

class GitHubAuthorizationRequiredForCloudHandoffError extends Error {
  constructor(
    message = "Connect GitHub before continuing this task in cloud.",
  ) {
    super(message);
    this.name = "GitHubAuthorizationRequiredForCloudHandoffError";
  }
}

type TrpcMutation = { mutate: (input?: any) => Promise<any> };
type TrpcQuery = { query: (input?: any) => Promise<any> };
type TrpcSubscription = {
  subscribe: (
    input: any,
    handlers: { onData: (data: any) => void; onError?: (err: unknown) => void },
  ) => { unsubscribe: () => void };
};

interface CloudHydrationResult {
  historyEntryCount: number;
  liveStreamLineCount: number;
}

interface CloudTaskWatcher {
  runId: string;
  apiHost: string;
  teamId: number;
  startToken: number;
  resumeFromEntryCount?: number;
  resumeHistoryCountOffset?: number;
  resumeHydrationToken: number;
  bufferResumeUpdates: boolean;
  bufferedResumeUpdates: CloudTaskUpdatePayload[];
  processCloudUpdate: (update: CloudTaskUpdatePayload) => void;
  subscription: { unsubscribe: () => void };
  onStatusChange?: () => void;
}

export interface SessionTrpc {
  agent: {
    start: TrpcMutation;
    reconnect: TrpcMutation;
    cancel: TrpcMutation;
    prompt: TrpcMutation;
    cancelPrompt: TrpcMutation;
    cancelPermission: TrpcMutation;
    respondToPermission: TrpcMutation;
    setConfigOption: TrpcMutation;
    resetAll: TrpcMutation;
    recordActivity: TrpcMutation;
    getPreviewConfigOptions: TrpcQuery;
    onSessionEvent: TrpcSubscription;
    onPermissionRequest: TrpcSubscription;
    onSessionIdleKilled: TrpcSubscription;
  };
  workspace: { verify: TrpcQuery };
  cloudTask: {
    watch: TrpcMutation;
    unwatch: TrpcMutation;
    retry: TrpcMutation;
    sendCommand: TrpcMutation;
    stop: TrpcMutation;
    designateRelayedMcpServers: TrpcMutation;
    onUpdate: TrpcSubscription;
  };
  handoff: {
    execute: TrpcMutation;
    executeToCloud: TrpcMutation;
    preflight: TrpcQuery;
    preflightToCloud: TrpcQuery;
  };
  logs: {
    readLocalLogs: TrpcQuery;
    /** Optional: merges superseded tool_call_update snapshots server-side so
     * a tool-heavy log doesn't ship its full redundant history over IPC.
     * Presence can't be trusted on proxy-based hosts (a tRPC client fabricates
     * a query for any path), so callers fall back to `readLocalLogs` when the
     * call itself fails. */
    readLocalLogsCollapsed?: TrpcQuery;
    /** Optional: only the Electron host exposes the tail read. Core feature-
     * detects and falls back to a full read when it's absent. */
    readLocalLogsTail?: TrpcQuery;
    fetchS3Logs: TrpcQuery;
    writeLocalLogs: TrpcMutation;
  };
  os: { openExternal: TrpcMutation };
}

export interface ISessionStore {
  setSession(session: AgentSession): void;
  removeSession(taskRunId: string): void;
  updateSession(taskRunId: string, updates: Partial<AgentSession>): void;
  appendEvents(
    taskRunId: string,
    events: AcpMessage[],
    newLineCount?: number,
  ): void;
  evictEvents(taskRunId: string): void;
  restoreEvents(
    taskRunId: string,
    events: AcpMessage[],
    lineCount: number,
  ): void;
  updateCloudStatus(
    taskRunId: string,
    fields: {
      status?: TaskRunStatus;
      stage?: string | null;
      output?: Record<string, unknown> | null;
      errorMessage?: string | null;
      branch?: string | null;
    },
  ): void;
  setPendingPermissions(
    taskRunId: string,
    permissions: Map<string, PermissionRequest>,
  ): void;
  enqueueMessage(
    taskId: string,
    content: string,
    rawPrompt?: string | ContentBlock[],
  ): void;
  removeQueuedMessage(taskId: string, messageId: string): void;
  updateQueuedMessage(
    taskId: string,
    messageId: string,
    patch: { content: string; rawPrompt?: string | ContentBlock[] },
  ): void;
  setEditingQueuedMessage(taskId: string, messageId: string): void;
  clearEditingQueuedMessage(taskId: string): void;
  clearMessageQueue(taskId: string): void;
  dequeueMessagesAsText(
    taskId: string,
    options?: { stopAtEdited?: boolean; max?: number },
  ): string | null;
  dequeueMessages(
    taskId: string,
    options?: { stopAtEdited?: boolean; max?: number },
  ): QueuedMessage[];
  prependQueuedMessages(taskId: string, messages: QueuedMessage[]): void;
  appendOptimisticItem(
    taskRunId: string,
    item: OptimisticItem extends infer T
      ? T extends { id: string }
        ? Omit<T, "id">
        : never
      : never,
  ): void;
  clearOptimisticItems(taskRunId: string): void;
  clearTailOptimisticItems(taskRunId: string): void;
  replaceOptimisticWithEvent(taskRunId: string, event: AcpMessage): void;
  getSessionByTaskId(taskId: string): AgentSession | undefined;
  getSessions(): Record<string, AgentSession>;
}

export interface SessionServiceHelpers {
  extractSkillButtonId: (...args: any[]) => any;
  combineQueuedCloudPrompts: (...args: any[]) => any;
  getCloudPromptTransport: (...args: any[]) => any;
  resolveLocalSkillCommandPrompt?: (prompt: string) => Promise<string | null>;
  uploadRunAttachments: (
    client: CloudArtifactClient,
    taskId: string,
    runId: string,
    filePaths: string[],
    skillBundles?: CloudSkillBundleRef[],
  ) => Promise<string[]>;
  uploadTaskStagedAttachments: (
    client: CloudArtifactClient,
    taskId: string,
    filePaths: string[],
    skillBundles?: CloudSkillBundleRef[],
  ) => Promise<string[]>;
}

export interface SessionServiceDeps {
  trpc: SessionTrpc;
  store: ISessionStore;
  h: SessionServiceHelpers;
  log: {
    info(message: string, data?: unknown): void;
    warn(message: string, data?: unknown): void;
    error(message: string, data?: unknown): void;
    debug(message: string, data?: unknown): void;
  };
  toast: {
    error: (msg: any, opts?: any) => unknown;
    info: (msg: any, opts?: any) => unknown;
  };
  track: (event: string, props?: Record<string, unknown>) => void;
  buildPermissionToolMetadata: (...args: any[]) => any;
  notifyPermissionRequest: (...args: any[]) => any;
  notifyPromptComplete: (...args: any[]) => any;
  enqueueSpeech: (request: {
    text: string;
    taskTitle: string;
    taskId?: string;
    kind: SpeechKind;
    source: SpeechSource;
    addressByName?: boolean;
  }) => void;
  getIsOnline: () => boolean;
  fetchAuthState: () => Promise<any>;
  getAuthenticatedClient: () => Promise<any>;
  createAuthenticatedClient: (authState: any) => any;
  getPersistedConfigOptions: (
    taskRunId: string,
  ) => SessionConfigOption[] | undefined;
  setPersistedConfigOptions: (
    taskRunId: string,
    options: SessionConfigOption[],
  ) => void;
  removePersistedConfigOptions: (taskRunId: string) => void;
  adapterStore: {
    getAdapter(taskRunId: string): Adapter | undefined;
    setAdapter(taskRunId: string, adapter: Adapter): void;
    removeAdapter(taskRunId: string): void;
  };
  readonly settings: {
    customInstructions?: string | null;
    rtkEnabledLocal?: boolean;
    rtkEnabledCloud?: boolean;
    spokenNotifications?: boolean;
    spokenNarrationEnabled?: boolean;
  };
  usageLimit: { show: (...args: any[]) => any };
  readonly addDirectoryDialog: { open: boolean };
  taskViewedApi: { markActivity(taskId: string): void };
  queryClient: {
    invalidateQueries: (filters?: any) => any;
    refetchQueries: (filters?: any) => any;
  };
  DEFAULT_GATEWAY_MODEL: string;
  WORKSPACE_QUERY_KEY: any;
}

type AuthClient = NonNullable<
  Awaited<ReturnType<SessionServiceDeps["getAuthenticatedClient"]>>
>;

interface AuthCredentials {
  apiHost: string;
  projectId: number;
  client: AuthClient;
}

type AuthCredentialsStatus =
  | { kind: "ready"; auth: AuthCredentials }
  | { kind: "restoring" }
  | { kind: "missing" };

export interface ConnectParams {
  task: Task;
  repoPath: string;
  initialPrompt?: ContentBlock[];
  executionMode?: ExecutionMode;
  adapter?: Adapter;
  model?: string;
  reasoningLevel?: string;
  /**
   * Session ID of an imported Claude Code CLI transcript already copied into
   * the app's Claude config dir. The agent loads it and replays its history.
   */
  importedSessionId?: string;
}

export interface CloudConnectionAuth {
  status: string;
  bootstrapComplete?: boolean;
  projectId?: number | null;
  cloudRegion?: CloudRegion | null;
}

export interface ReconcileSessionState {
  taskRunId: string;
  taskId: string;
  taskTitle: string;
  status: AgentSession["status"];
  isCloud?: boolean;
  idleKilled?: boolean;
  eventCount: number;
}

export interface ReconcileTaskConnectionParams {
  task: Task;
  session: ReconcileSessionState | undefined;
  repoPath: string | null;
  isCloud: boolean;
  isSuspended?: boolean;
  isOnline: boolean;
  cloudAuth: CloudConnectionAuth;
  onCloudStatusChange?: () => void;
}

const ACTIVITY_HEARTBEAT_INTERVAL_MS = 5 * 60 * 1000;

export type SessionPlan = Extract<SessionUpdate, { sessionUpdate: "plan" }>;

export function selectLatestPlan(events: AcpMessage[]): SessionPlan | null {
  let planIndex = -1;
  let plan: SessionPlan | null = null;
  let turnEndResponseIndex = -1;

  for (let i = events.length - 1; i >= 0; i--) {
    const msg = events[i].message;

    if (
      turnEndResponseIndex === -1 &&
      isJsonRpcResponse(msg) &&
      (msg.result as { stopReason?: string })?.stopReason !== undefined
    ) {
      turnEndResponseIndex = i;
    }

    if (
      planIndex === -1 &&
      isJsonRpcNotification(msg) &&
      msg.method === "session/update"
    ) {
      const update = (msg.params as { update?: { sessionUpdate?: string } })
        ?.update;
      if (update?.sessionUpdate === "plan") {
        planIndex = i;
        plan = update as SessionPlan;
      }
    }

    if (planIndex !== -1 && turnEndResponseIndex !== -1) break;
  }

  if (turnEndResponseIndex > planIndex) return null;

  return plan;
}

export function createLatestPlanTracker() {
  return createAppendOnlyTracker<
    { plan: SessionPlan | null },
    SessionPlan | null
  >({
    init: () => ({ plan: null }),
    processEvent: (state, event) => {
      const msg = event.message;

      if (
        isJsonRpcResponse(msg) &&
        (msg.result as { stopReason?: string })?.stopReason !== undefined
      ) {
        state.plan = null;
        return;
      }

      if (isJsonRpcNotification(msg) && msg.method === "session/update") {
        const update = (msg.params as { update?: { sessionUpdate?: string } })
          ?.update;
        if (update?.sessionUpdate === "plan") {
          state.plan = update as SessionPlan;
        }
      }
    },
    getResult: (state) => state.plan,
  });
}

export const SESSION_SERVICE = Symbol.for("posthog.core.sessions.service");

type DerivedPermissionRequest = Pick<
  CloudTaskPermissionRequestUpdate,
  "requestId" | "toolCall" | "options"
>;

function getEntryTaskRunMarker(entry: StoredLogEntry): string | undefined {
  const method = entry.notification?.method;
  if (!method) return undefined;

  const params = (entry.notification?.params ?? {}) as {
    runId?: unknown;
    taskRunId?: unknown;
  };

  if (
    isNotification(method, POSTHOG_NOTIFICATIONS.SDK_SESSION) &&
    typeof params.taskRunId === "string"
  ) {
    return params.taskRunId;
  }

  if (
    isNotification(method, POSTHOG_NOTIFICATIONS.RUN_STARTED) &&
    typeof params.runId === "string"
  ) {
    return params.runId;
  }

  return undefined;
}

function entriesScopedToTaskRun(
  entries: StoredLogEntry[],
  taskRunId: string | undefined,
): StoredLogEntry[] {
  if (!taskRunId || !entries.some((entry) => getEntryTaskRunMarker(entry))) {
    return entries;
  }

  let currentTaskRunId: string | undefined;
  return entries.filter((entry) => {
    const marker = getEntryTaskRunMarker(entry);
    if (marker) {
      currentTaskRunId = marker;
    }
    return currentTaskRunId === taskRunId;
  });
}

function suffixPrefixOverlap(left: string[], right: string[]): number {
  if (left.length === 0 || right.length === 0) return 0;

  const separator = Symbol("resume-chain-separator");
  const patternAndTail: (string | symbol)[] = [
    ...right,
    separator,
    ...left.slice(-right.length),
  ];
  const prefixLengths = new Array<number>(patternAndTail.length).fill(0);
  for (let index = 1; index < patternAndTail.length; index += 1) {
    let prefixLength = prefixLengths[index - 1];
    while (
      prefixLength > 0 &&
      patternAndTail[index] !== patternAndTail[prefixLength]
    ) {
      prefixLength = prefixLengths[prefixLength - 1];
    }
    if (patternAndTail[index] === patternAndTail[prefixLength]) {
      prefixLength += 1;
    }
    prefixLengths[index] = prefixLength;
  }
  return prefixLengths[prefixLengths.length - 1];
}

function appendHydrationHash(hash: number, value: string): number {
  let nextHash = hash;
  for (let index = 0; index < value.length; index += 1) {
    nextHash ^= value.charCodeAt(index);
    nextHash = Math.imul(nextHash, 16_777_619);
  }
  return nextHash >>> 0;
}

function hashHydrationValue(value: unknown, hash = 2_166_136_261): number {
  if (value === null) return appendHydrationHash(hash, "null");
  if (Array.isArray(value)) {
    let nextHash = appendHydrationHash(hash, "[");
    for (const item of value) {
      nextHash = hashHydrationValue(item, nextHash);
      nextHash = appendHydrationHash(nextHash, ",");
    }
    return appendHydrationHash(nextHash, "]");
  }
  switch (typeof value) {
    case "boolean":
      return appendHydrationHash(hash, value ? "true" : "false");
    case "number":
      return appendHydrationHash(hash, `number:${value}`);
    case "string":
      return appendHydrationHash(hash, `string:${value}`);
    case "undefined":
      return appendHydrationHash(hash, "undefined");
    case "object": {
      let nextHash = appendHydrationHash(hash, "{");
      const record = value as Record<string, unknown>;
      for (const key of Object.keys(record).sort()) {
        nextHash = appendHydrationHash(nextHash, key);
        nextHash = hashHydrationValue(record[key], nextHash);
      }
      return appendHydrationHash(nextHash, "}");
    }
    default:
      return appendHydrationHash(hash, typeof value);
  }
}

function hydrationValuesEqual(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (left === null || right === null || typeof left !== typeof right) {
    return false;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right)) return false;
    return (
      left.length === right.length &&
      left.every((value, index) => hydrationValuesEqual(value, right[index]))
    );
  }
  if (typeof left !== "object" || typeof right !== "object") return false;
  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord);
  const rightKeys = Object.keys(rightRecord);
  return (
    leftKeys.length === rightKeys.length &&
    leftKeys.every(
      (key) =>
        Object.hasOwn(rightRecord, key) &&
        hydrationValuesEqual(leftRecord[key], rightRecord[key]),
    )
  );
}

function cloudHydrationMessageHash(event: AcpMessage): number {
  return hashHydrationValue(event.message);
}

function cloudHydrationMessagesEqual(
  left: AcpMessage,
  right: AcpMessage,
): boolean {
  const leftPosition = getStoredLogEventPosition(left);
  const rightPosition = getStoredLogEventPosition(right);
  if (leftPosition && rightPosition) {
    return (
      leftPosition.taskRunId === rightPosition.taskRunId &&
      leftPosition.entryIndex === rightPosition.entryIndex
    );
  }
  return hydrationValuesEqual(left.message, right.message);
}

function cloudHydrationPositionsEqual(
  left: AcpMessage,
  right: AcpMessage,
): boolean {
  const leftPosition = getStoredLogEventPosition(left);
  const rightPosition = getStoredLogEventPosition(right);
  return (
    leftPosition !== undefined &&
    rightPosition !== undefined &&
    leftPosition.taskRunId === rightPosition.taskRunId &&
    leftPosition.entryIndex === rightPosition.entryIndex
  );
}

interface HydrationTurn {
  events: AcpMessage[];
  eventHashes: number[];
  promptEvent?: AcpMessage;
  promptHash?: number;
  taskRunId?: string;
}

interface HydrationPromptPositions {
  all: number[];
  unscoped: number[];
  byTaskRunId: Map<string, number[]>;
}

function sessionEventTaskRunMarker(event: AcpMessage): string | undefined {
  if (!isJsonRpcNotification(event.message)) return undefined;
  const params = (event.message.params ?? {}) as {
    runId?: unknown;
    taskRunId?: unknown;
  };
  if (
    isNotification(event.message.method, POSTHOG_NOTIFICATIONS.SDK_SESSION) &&
    typeof params.taskRunId === "string"
  ) {
    return params.taskRunId;
  }
  if (
    isNotification(event.message.method, POSTHOG_NOTIFICATIONS.RUN_STARTED) &&
    typeof params.runId === "string"
  ) {
    return params.runId;
  }
  return undefined;
}

function splitHydrationTurns(events: AcpMessage[]): HydrationTurn[] {
  const turns: HydrationTurn[] = [];
  let taskRunId: string | undefined;
  let currentEvents: AcpMessage[] = [];
  let currentPromptEvent: AcpMessage | undefined;
  const finishCurrent = (): void => {
    if (currentEvents.length === 0) return;
    turns.push({
      events: currentEvents,
      eventHashes: currentEvents.map(cloudHydrationMessageHash),
      promptEvent: currentPromptEvent,
      promptHash: currentPromptEvent
        ? cloudHydrationMessageHash(currentPromptEvent)
        : undefined,
      taskRunId,
    });
  };

  for (const event of events) {
    const marker = sessionEventTaskRunMarker(event);
    if (marker) {
      finishCurrent();
      taskRunId = marker;
      currentEvents = [event];
      currentPromptEvent = undefined;
      continue;
    }

    if (isSessionPromptEvent(event)) {
      finishCurrent();
      currentEvents = [event];
      currentPromptEvent = event;
      continue;
    }
    currentEvents.push(event);
  }
  finishCurrent();
  return turns;
}

function hydrationTurnScopesMatch(
  liveTurn: HydrationTurn,
  hydratedTurn: HydrationTurn,
): boolean {
  return (
    liveTurn.taskRunId === undefined ||
    hydratedTurn.taskRunId === undefined ||
    liveTurn.taskRunId === hydratedTurn.taskRunId
  );
}

function indexHydratedPromptTurns(
  hydratedTurns: HydrationTurn[],
): Map<number, HydrationPromptPositions> {
  const positionsByPrompt = new Map<number, HydrationPromptPositions>();
  for (let index = 0; index < hydratedTurns.length; index += 1) {
    const turn = hydratedTurns[index];
    if (turn.promptHash === undefined) continue;
    let positions = positionsByPrompt.get(turn.promptHash);
    if (!positions) {
      positions = {
        all: [],
        unscoped: [],
        byTaskRunId: new Map(),
      };
      positionsByPrompt.set(turn.promptHash, positions);
    }
    positions.all.push(index);
    if (turn.taskRunId === undefined) {
      positions.unscoped.push(index);
      continue;
    }
    const scopedPositions = positions.byTaskRunId.get(turn.taskRunId) ?? [];
    scopedPositions.push(index);
    positions.byTaskRunId.set(turn.taskRunId, scopedPositions);
  }
  return positionsByPrompt;
}

function latestPositionIndexAtOrBefore(
  positions: number[] | undefined,
  maximum: number,
): number {
  if (!positions || positions.length === 0) return -1;
  let low = 0;
  let high = positions.length - 1;
  let match = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (positions[middle] <= maximum) {
      match = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return match;
}

function findPromptHydrationTurn(
  liveTurn: HydrationTurn,
  hydratedTurns: HydrationTurn[],
  positionsByPrompt: Map<number, HydrationPromptPositions>,
  maximum: number,
): number {
  const livePrompt = liveTurn.promptEvent;
  if (livePrompt === undefined || liveTurn.promptHash === undefined) {
    return -1;
  }
  const positions = positionsByPrompt.get(liveTurn.promptHash);
  if (!positions) return -1;
  const matchingPosition = (
    candidatePositions: number[] | undefined,
  ): number => {
    if (!candidatePositions) return -1;
    let candidateIndex = latestPositionIndexAtOrBefore(
      candidatePositions,
      maximum,
    );
    while (candidateIndex >= 0) {
      const position = candidatePositions[candidateIndex];
      const hydratedPrompt = hydratedTurns[position].promptEvent;
      if (
        hydratedPrompt &&
        cloudHydrationMessagesEqual(livePrompt, hydratedPrompt)
      ) {
        return position;
      }
      candidateIndex -= 1;
    }
    return -1;
  };
  if (liveTurn.taskRunId === undefined) {
    return matchingPosition(positions.all);
  }
  return Math.max(
    matchingPosition(positions.byTaskRunId.get(liveTurn.taskRunId)),
    matchingPosition(positions.unscoped),
  );
}

interface PromptlessHydrationMatch {
  hydratedTurnIndex: number;
  liveMessageIndexOffset: number;
}

interface HydrationEventOverlap {
  hydratedEventIndex: number;
  liveEventIndex: number;
}

interface HydrationEventPosition {
  turnIndex: number;
  eventIndex: number;
}

type HydrationEventIndex = Map<number, HydrationEventPosition[]>;

function indexHydratedTurnEvents(
  hydratedTurns: HydrationTurn[],
): HydrationEventIndex {
  const positionsByHash: HydrationEventIndex = new Map();
  for (let turnIndex = 0; turnIndex < hydratedTurns.length; turnIndex += 1) {
    const turn = hydratedTurns[turnIndex];
    for (let eventIndex = 0; eventIndex < turn.events.length; eventIndex += 1) {
      if (!isStrongPromptlessOverlapEvent(turn.events[eventIndex])) continue;
      const hash = turn.eventHashes[eventIndex];
      const positions = positionsByHash.get(hash) ?? [];
      positions.push({ turnIndex, eventIndex });
      positionsByHash.set(hash, positions);
    }
  }
  return positionsByHash;
}

function isStrongPromptlessOverlapEvent(event: AcpMessage): boolean {
  if (!isJsonRpcNotification(event.message)) return false;
  if (event.message.method !== "session/update") return false;
  const update = (
    event.message.params as { update?: { sessionUpdate?: unknown } } | undefined
  )?.update;
  return (
    typeof update?.sessionUpdate === "string" &&
    agentMessageUpdateKind(event) !== "ignored"
  );
}

function findHydrationEventOverlap(
  liveTurn: HydrationTurn,
  hydratedTurn: HydrationTurn,
  allowWeakOverlap: boolean,
): HydrationEventOverlap | undefined {
  if (!hydrationTurnScopesMatch(liveTurn, hydratedTurn)) return undefined;
  const hydratedPositions = new Map<number, number[]>();
  for (
    let hydratedIndex = 0;
    hydratedIndex < hydratedTurn.events.length;
    hydratedIndex += 1
  ) {
    const event = hydratedTurn.events[hydratedIndex];
    if (!allowWeakOverlap && !isStrongPromptlessOverlapEvent(event)) {
      continue;
    }
    const hash = hydratedTurn.eventHashes[hydratedIndex];
    const positions = hydratedPositions.get(hash) ?? [];
    positions.push(hydratedIndex);
    hydratedPositions.set(hash, positions);
  }
  const findMatch = (
    kind: "stable" | "boundary" | "any",
  ): HydrationEventOverlap | undefined => {
    for (
      let liveIndex = liveTurn.events.length - 1;
      liveIndex >= 0;
      liveIndex -= 1
    ) {
      const liveEvent = liveTurn.events[liveIndex];
      if (!allowWeakOverlap && !isStrongPromptlessOverlapEvent(liveEvent)) {
        continue;
      }
      if (
        kind === "boundary" &&
        (!isStrongPromptlessOverlapEvent(liveEvent) ||
          agentMessageUpdateKind(liveEvent) != null)
      ) {
        continue;
      }
      const positions = hydratedPositions.get(liveTurn.eventHashes[liveIndex]);
      if (!positions) continue;
      for (
        let positionIndex = positions.length - 1;
        positionIndex >= 0;
        positionIndex -= 1
      ) {
        const hydratedEventIndex = positions[positionIndex];
        const hydratedEvent = hydratedTurn.events[hydratedEventIndex];
        if (
          kind === "stable" &&
          !cloudHydrationPositionsEqual(liveEvent, hydratedEvent)
        ) {
          continue;
        }
        if (cloudHydrationMessagesEqual(liveEvent, hydratedEvent)) {
          return { hydratedEventIndex, liveEventIndex: liveIndex };
        }
      }
    }
    return undefined;
  };
  return findMatch("stable") ?? findMatch("boundary") ?? findMatch("any");
}

function agentMessageIndexBeforeEvent(
  events: AcpMessage[],
  eventIndex: number,
): number {
  const position: AgentMessagePosition = {
    messageIndex: 0,
    chunkRunActive: false,
  };
  for (let index = 0; index < eventIndex; index += 1) {
    const updateKind = agentMessageUpdateKind(events[index]);
    if (updateKind === "ignored") continue;
    if (updateKind === "chunk") {
      position.chunkRunActive = true;
    } else if (updateKind === "final") {
      position.messageIndex += 1;
      position.chunkRunActive = false;
    } else {
      finishAgentMessageChunkRun(position);
    }
  }
  return position.messageIndex;
}

function indexAgentMessagePositions(
  events: AcpMessage[],
  startingIndex: number,
): WeakMap<AcpMessage, number> {
  const positions = new WeakMap<AcpMessage, number>();
  const position: AgentMessagePosition = {
    messageIndex: startingIndex,
    chunkRunActive: false,
  };
  for (const event of events) {
    const updateKind = agentMessageUpdateKind(event);
    if (updateKind === "chunk") {
      positions.set(event, position.messageIndex);
      position.chunkRunActive = true;
    } else if (updateKind === "final") {
      positions.set(event, position.messageIndex);
      position.messageIndex += 1;
      position.chunkRunActive = false;
    } else if (updateKind !== "ignored") {
      finishAgentMessageChunkRun(position);
    }
  }
  return positions;
}

function promptlessTailStrictlyPredatesPrompt(
  liveTurn: HydrationTurn,
  hydratedTurn: HydrationTurn,
): boolean {
  const promptTimestamp = hydratedTurn.promptEvent?.ts;
  return (
    promptTimestamp === undefined ||
    liveTurn.events.every((event) => event.ts < promptTimestamp)
  );
}

function hasLaterUnmatchedAssistantBoundary(
  liveTurn: HydrationTurn,
  hydratedTurn: HydrationTurn,
  overlap: HydrationEventOverlap,
): boolean {
  if (agentMessageUpdateKind(liveTurn.events[overlap.liveEventIndex]) == null) {
    return false;
  }
  return hydratedTurn.events
    .slice(overlap.hydratedEventIndex + 1)
    .some(
      (event) =>
        isStrongPromptlessOverlapEvent(event) &&
        agentMessageUpdateKind(event) == null,
    );
}

interface IndexedHydrationEventOverlap extends HydrationEventOverlap {
  hydratedTurnIndex: number;
}

function latestEventPositionAtOrBeforeTurn(
  positions: HydrationEventPosition[],
  maximumTurnIndex: number,
): number {
  let low = 0;
  let high = positions.length - 1;
  let match = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (positions[middle].turnIndex <= maximumTurnIndex) {
      match = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return match;
}

function findIndexedPromptlessOverlap(
  liveTurn: HydrationTurn,
  hydratedTurns: HydrationTurn[],
  hydratedEventIndex: HydrationEventIndex,
  minimumTurnIndex: number,
  maximumTurnIndex: number,
): IndexedHydrationEventOverlap | undefined {
  let latestMatch: IndexedHydrationEventOverlap | undefined;
  for (
    let liveEventIndex = liveTurn.events.length - 1;
    liveEventIndex >= 0;
    liveEventIndex -= 1
  ) {
    const liveEvent = liveTurn.events[liveEventIndex];
    if (!isStrongPromptlessOverlapEvent(liveEvent)) continue;
    const positions = hydratedEventIndex.get(
      liveTurn.eventHashes[liveEventIndex],
    );
    if (!positions) continue;
    for (
      let positionIndex = latestEventPositionAtOrBeforeTurn(
        positions,
        maximumTurnIndex,
      );
      positionIndex >= 0;
      positionIndex -= 1
    ) {
      const position = positions[positionIndex];
      if (position.turnIndex < minimumTurnIndex) break;
      if (latestMatch && position.turnIndex < latestMatch.hydratedTurnIndex) {
        break;
      }
      const hydratedTurn = hydratedTurns[position.turnIndex];
      const hydratedEvent = hydratedTurn.events[position.eventIndex];
      if (
        !isStrongPromptlessOverlapEvent(hydratedEvent) ||
        !hydrationTurnScopesMatch(liveTurn, hydratedTurn) ||
        !cloudHydrationMessagesEqual(liveEvent, hydratedEvent)
      ) {
        continue;
      }
      latestMatch = {
        hydratedTurnIndex: position.turnIndex,
        hydratedEventIndex: position.eventIndex,
        liveEventIndex,
      };
      break;
    }
  }
  return latestMatch;
}

function findPromptlessHydrationTurn(
  liveTurn: HydrationTurn,
  hydratedTurns: HydrationTurn[],
  hydratedEventIndex: HydrationEventIndex,
  maximum: number,
): PromptlessHydrationMatch | undefined {
  if (maximum < 0) return undefined;
  const leafTaskRunId = hydratedTurns[maximum]?.taskRunId;
  let minimum = 0;
  if (leafTaskRunId !== undefined) {
    minimum = maximum;
    while (
      minimum > 0 &&
      hydratedTurns[minimum - 1].taskRunId === leafTaskRunId
    ) {
      minimum -= 1;
    }
  }
  const newestHydratedTurn = hydratedTurns[maximum];
  const newestOverlap = findHydrationEventOverlap(
    liveTurn,
    newestHydratedTurn,
    true,
  );
  if (newestOverlap) {
    if (
      !cloudHydrationPositionsEqual(
        liveTurn.events[newestOverlap.liveEventIndex],
        newestHydratedTurn.events[newestOverlap.hydratedEventIndex],
      ) &&
      hasLaterUnmatchedAssistantBoundary(
        liveTurn,
        newestHydratedTurn,
        newestOverlap,
      )
    ) {
      return undefined;
    }
    return {
      hydratedTurnIndex: maximum,
      liveMessageIndexOffset:
        agentMessageIndexBeforeEvent(
          newestHydratedTurn.events,
          newestOverlap.hydratedEventIndex,
        ) -
        agentMessageIndexBeforeEvent(
          liveTurn.events,
          newestOverlap.liveEventIndex,
        ),
    };
  }
  if (maximum === minimum) {
    return undefined;
  }
  const olderOverlap = findIndexedPromptlessOverlap(
    liveTurn,
    hydratedTurns,
    hydratedEventIndex,
    minimum,
    maximum - 1,
  );
  if (!olderOverlap) return undefined;
  const hydratedTurn = hydratedTurns[olderOverlap.hydratedTurnIndex];
  const hasStableOverlap = cloudHydrationPositionsEqual(
    liveTurn.events[olderOverlap.liveEventIndex],
    hydratedTurn.events[olderOverlap.hydratedEventIndex],
  );
  if (
    !hasStableOverlap &&
    !promptlessTailStrictlyPredatesPrompt(liveTurn, newestHydratedTurn)
  ) {
    return undefined;
  }
  return {
    hydratedTurnIndex: olderOverlap.hydratedTurnIndex,
    liveMessageIndexOffset:
      agentMessageIndexBeforeEvent(
        hydratedTurn.events,
        olderOverlap.hydratedEventIndex,
      ) -
      agentMessageIndexBeforeEvent(
        liveTurn.events,
        olderOverlap.liveEventIndex,
      ),
  };
}

function discardExactHydratedEvents(
  liveTurn: Pick<HydrationTurn, "events" | "eventHashes">,
  hydratedTurn: Pick<HydrationTurn, "events" | "eventHashes">,
  liveMessagePositions: WeakMap<AcpMessage, number>,
  hydratedMessagePositions: WeakMap<AcpMessage, number>,
): AcpMessage[] {
  const keep = new Array<boolean>(liveTurn.events.length).fill(true);
  const hydratedPositions = new Map<number, number[]>();
  for (let index = 0; index < hydratedTurn.eventHashes.length; index += 1) {
    const eventHash = hydratedTurn.eventHashes[index];
    const positions = hydratedPositions.get(eventHash) ?? [];
    positions.push(index);
    hydratedPositions.set(eventHash, positions);
  }
  let hydratedIndex = hydratedTurn.eventHashes.length - 1;
  for (
    let liveIndex = liveTurn.eventHashes.length - 1;
    liveIndex >= 0;
    liveIndex -= 1
  ) {
    const positions = hydratedPositions.get(liveTurn.eventHashes[liveIndex]);
    if (!positions) continue;
    let positionIndex = latestPositionIndexAtOrBefore(positions, hydratedIndex);
    while (positionIndex >= 0) {
      const matchedIndex = positions[positionIndex];
      const liveMessagePosition = liveMessagePositions.get(
        liveTurn.events[liveIndex],
      );
      const hydratedMessagePosition = hydratedMessagePositions.get(
        hydratedTurn.events[matchedIndex],
      );
      if (
        (liveMessagePosition !== undefined ||
          hydratedMessagePosition !== undefined) &&
        liveMessagePosition !== hydratedMessagePosition
      ) {
        positionIndex -= 1;
        continue;
      }
      if (
        cloudHydrationMessagesEqual(
          liveTurn.events[liveIndex],
          hydratedTurn.events[matchedIndex],
        )
      ) {
        keep[liveIndex] = false;
        hydratedIndex = matchedIndex - 1;
        break;
      }
      positionIndex -= 1;
    }
  }
  return liveTurn.events.filter((_event, index) => keep[index]);
}

function agentMessageUpdateKind(
  event: AcpMessage,
): "final" | "chunk" | "ignored" | undefined {
  const message = event.message;
  if (!isJsonRpcNotification(message) || message.method !== "session/update") {
    return undefined;
  }
  const update = (
    message.params as
      | {
          update?: {
            sessionUpdate?: string;
            content?: unknown;
          };
        }
      | undefined
  )?.update;
  if (update?.sessionUpdate === "agent_message") return "final";
  if (update?.sessionUpdate === "agent_message_chunk") return "chunk";
  if (update?.sessionUpdate === "agent_thought_chunk") {
    const content = update.content as
      | { type?: string; text?: string; thinking?: string }
      | null
      | undefined;
    if (
      (content?.type === "text" && !content.text) ||
      (content?.type === "thinking" && !content.thinking)
    ) {
      return "ignored";
    }
  }
  return undefined;
}

interface AgentMessagePosition {
  messageIndex: number;
  chunkRunActive: boolean;
}

function isSessionPromptEvent(event: AcpMessage): boolean {
  return (
    isJsonRpcRequest(event.message) && event.message.method === "session/prompt"
  );
}

function finishAgentMessageChunkRun(position: AgentMessagePosition): void {
  if (!position.chunkRunActive) return;
  position.messageIndex += 1;
  position.chunkRunActive = false;
}

function discardChunksSupersededByHydratedMessages(
  liveTurn: HydrationTurn,
  hydratedTurn: HydrationTurn,
  liveMessageIndexOffset: number,
): Pick<HydrationTurn, "events" | "eventHashes"> {
  const hydratedMessagePositions = new Set<number>();
  const hydratedPosition: AgentMessagePosition = {
    messageIndex: 0,
    chunkRunActive: false,
  };
  for (const event of hydratedTurn.events) {
    if (isSessionPromptEvent(event)) continue;
    const updateKind = agentMessageUpdateKind(event);
    if (updateKind === "ignored") continue;
    if (updateKind === "chunk") {
      hydratedPosition.chunkRunActive = true;
      continue;
    }
    if (updateKind === "final") {
      hydratedMessagePositions.add(hydratedPosition.messageIndex);
      hydratedPosition.messageIndex += 1;
      hydratedPosition.chunkRunActive = false;
      continue;
    }
    finishAgentMessageChunkRun(hydratedPosition);
  }

  // SessionLogWriter treats consecutive chunks as one assistant message. A
  // direct agent_message replaces that buffered message, while a later chunk
  // run after a tool/update boundary is a separate message. Match those
  // turn-local message positions instead of timestamps so direct finals and
  // same-millisecond events reconcile correctly.
  const livePosition: AgentMessagePosition = {
    messageIndex: Math.max(0, liveMessageIndexOffset),
    chunkRunActive: false,
  };
  let discardChunkRun = false;
  const events: AcpMessage[] = [];
  const eventHashes: number[] = [];
  for (
    let eventIndex = 0;
    eventIndex < liveTurn.events.length;
    eventIndex += 1
  ) {
    const event = liveTurn.events[eventIndex];
    let keep = true;
    if (isSessionPromptEvent(event)) {
      discardChunkRun = false;
    } else {
      const updateKind = agentMessageUpdateKind(event);
      if (updateKind === "chunk") {
        if (!livePosition.chunkRunActive) {
          livePosition.chunkRunActive = true;
          discardChunkRun = hydratedMessagePositions.has(
            livePosition.messageIndex,
          );
        }
        keep = !discardChunkRun;
      } else if (updateKind === "final") {
        livePosition.messageIndex += 1;
        livePosition.chunkRunActive = false;
        discardChunkRun = false;
      } else if (updateKind !== "ignored") {
        finishAgentMessageChunkRun(livePosition);
        discardChunkRun = false;
      }
    }
    if (keep) {
      events.push(event);
      eventHashes.push(liveTurn.eventHashes[eventIndex]);
    }
  }
  return { events, eventHashes };
}

export function reconcileLiveEventsWithHydratedEvents(
  liveEvents: AcpMessage[],
  hydratedEvents: AcpMessage[],
): AcpMessage[] {
  const liveTurns = splitHydrationTurns(liveEvents);
  const hydratedTurns = splitHydrationTurns(hydratedEvents);
  const promptPositions = indexHydratedPromptTurns(hydratedTurns);
  const hydratedEventIndex = indexHydratedTurnEvents(hydratedTurns);
  const reconciledTurns = new Array<AcpMessage[]>(liveTurns.length);
  let hydratedTurnIndex = hydratedTurns.length - 1;

  for (
    let liveTurnIndex = liveTurns.length - 1;
    liveTurnIndex >= 0;
    liveTurnIndex -= 1
  ) {
    const liveTurn = liveTurns[liveTurnIndex];
    let liveMessageIndexOffset = 0;
    let matchedHydratedTurnIndex = findPromptHydrationTurn(
      liveTurn,
      hydratedTurns,
      promptPositions,
      hydratedTurnIndex,
    );
    if (liveTurn.promptEvent === undefined) {
      const promptlessMatch = findPromptlessHydrationTurn(
        liveTurn,
        hydratedTurns,
        hydratedEventIndex,
        hydratedTurnIndex,
      );
      if (promptlessMatch) {
        matchedHydratedTurnIndex = promptlessMatch.hydratedTurnIndex;
        liveMessageIndexOffset = promptlessMatch.liveMessageIndexOffset;
      }
    }
    if (matchedHydratedTurnIndex === -1) {
      reconciledTurns[liveTurnIndex] = liveTurn.events;
      continue;
    }

    const hydratedTurn = hydratedTurns[matchedHydratedTurnIndex];
    const liveMessagePositions = indexAgentMessagePositions(
      liveTurn.events,
      Math.max(0, liveMessageIndexOffset),
    );
    const hydratedMessagePositions = indexAgentMessagePositions(
      hydratedTurn.events,
      0,
    );
    reconciledTurns[liveTurnIndex] = discardExactHydratedEvents(
      discardChunksSupersededByHydratedMessages(
        liveTurn,
        hydratedTurn,
        liveMessageIndexOffset,
      ),
      hydratedTurn,
      liveMessagePositions,
      hydratedMessagePositions,
    );
    hydratedTurnIndex = matchedHydratedTurnIndex - 1;
  }

  return reconciledTurns.flat();
}

export function derivePendingPermissionRequests(
  entries: StoredLogEntry[],
  options?: { taskRunId?: string },
): DerivedPermissionRequest[] {
  const requests = new Map<string, DerivedPermissionRequest>();
  const resolved = new Set<string>();
  for (const entry of entriesScopedToTaskRun(entries, options?.taskRunId)) {
    const method = entry.notification?.method;
    if (!method) continue;
    const params = (entry.notification?.params ?? {}) as {
      requestId?: string;
      toolCall?: CloudTaskPermissionRequestUpdate["toolCall"];
      options?: CloudTaskPermissionRequestUpdate["options"];
    };
    if (typeof params.requestId !== "string") continue;
    if (isNotification(method, POSTHOG_NOTIFICATIONS.PERMISSION_RESOLVED)) {
      resolved.add(params.requestId);
    } else if (
      isNotification(method, POSTHOG_NOTIFICATIONS.PERMISSION_REQUEST) &&
      typeof params.toolCall?.toolCallId === "string" &&
      Array.isArray(params.options)
    ) {
      requests.set(params.requestId, {
        requestId: params.requestId,
        toolCall: params.toolCall,
        options: params.options,
      });
    }
  }
  return [...requests.values()].filter((r) => !resolved.has(r.requestId));
}

/**
 * Whether a derived permission request has already been surfaced for this
 * session. Snapshot replays re-deliver still-pending requests on every
 * bootstrap and re-subscribe; only the first delivery should notify. A
 * different requestId for the same tool call is a new ask and must notify.
 */
export function isPermissionRequestAlreadySurfaced(
  pendingPermissions: ReadonlyMap<string, unknown>,
  trackedRequestId: string | undefined,
  update: DerivedPermissionRequest,
): boolean {
  return (
    trackedRequestId === update.requestId &&
    pendingPermissions.has(update.toolCall.toolCallId)
  );
}

/** The steering capability on a loosely-typed agent start/reconnect result. */
function readSteering(result: unknown): string | undefined {
  return (result as { steering?: string } | undefined)?.steering;
}

function classifyTurnEventKind(
  msg: AcpMessage["message"],
): "text" | "output" | "other" {
  if (!("method" in msg) || msg.method !== "session/update") return "other";
  const update = (msg as { params?: { update?: Record<string, unknown> } })
    .params?.update;
  if (!update) return "other";
  const sessionUpdate = update.sessionUpdate;
  if (sessionUpdate === "agent_message_chunk") {
    const content = update.content as { type?: string } | undefined;
    return content?.type === "text" ? "text" : "output";
  }
  if (
    sessionUpdate === "agent_thought_chunk" ||
    sessionUpdate === "tool_call" ||
    sessionUpdate === "tool_call_update"
  ) {
    return "output";
  }
  return "other";
}

export class SessionService {
  private connectingTasks = new Map<string, Promise<void>>();
  private reconcilingTasks = new Set<string>();
  private reconcileSkipLogged = new Set<string>();
  private taskCreationMarks = new Map<string, number>();
  private static readonly TASK_CREATION_IN_FLIGHT_TTL_MS = 10 * 60 * 1000;
  private activityHeartbeats = new Map<
    string,
    ReturnType<typeof setInterval>
  >();
  private localRepoPaths = new Map<string, string>();
  private localRecoveryAttempts = new Map<string, Promise<boolean>>();
  private sessionLastUsedAt = new Map<string, number>();
  private mountedTaskCounts = new Map<string, number>();
  /** Re-entrance guard for cloud queue dispatch (per taskId). */
  private dispatchingCloudQueues = new Set<string>();
  /** Coalesces deferred cloud queue flush timers (per taskId). */
  private scheduledCloudQueueFlushes = new Set<string>();
  private cloudRunIdleTracker: CloudRunIdleTracker;
  private nextCloudTaskWatchToken = 0;
  private supersededRunIds = new Set<string>();
  // Spoken narration: the `speak` tool's { text, kind } args stream in across
  // multiple tool_call_updates (partial input_json_delta), so early events carry
  // a truncated text like "The quick b". Track speak tool calls by id and
  // accumulate their latest args; enqueue once the call reaches a terminal
  // status (full text), then delete the entry — which also dedupes re-fires.
  // A `null` value means "identified as speak, args not streamed in yet".
  // Keyed by taskRunId first so a session teardown can drop any of its
  // still-streaming speak calls (see unsubscribeFromChannel); the inner map is
  // keyed by toolCallId.
  private speakCalls = new Map<
    string,
    Map<string, { text: string; kind: SpeechKind } | null>
  >();
  // When the agent last narrated `done`/`needs_input` per task run (event ts).
  // The deterministic completion/needs-input backstops compare this against the
  // turn's start so they don't double up on a moment the agent already voiced.
  private agentSpokeAt = new Map<
    string,
    { needs_input: number; done: number }
  >();
  private subscriptions = new Map<
    string,
    {
      event: { unsubscribe: () => void };
      permission?: { unsubscribe: () => void };
    }
  >();
  /** Active cloud task watchers, keyed by taskId */
  private cloudTaskWatchers = new Map<string, CloudTaskWatcher>();
  private cloudLogGapReconciler: CloudLogGapReconciler;
  /** Maps toolCallId → cloud requestId for routing permission responses */
  private cloudPermissionRequestIds = new Map<string, string>();
  /**
   * Cloud permission requestIds the user has already responded to this app
   * session. A stale snapshot (a resolved marker not yet flushed to storage)
   * or a replayed stream frame can re-deliver an answered request; without
   * this guard it would re-surface as a fresh pending card.
   */
  private respondedCloudPermissionRequestIds = new Set<string>();
  private liveTurnContent = new Map<
    string,
    { startedAtTs: number; agentTextChunks: number; agentOutputEvents: number }
  >();
  private pendingPermissionHydratedRuns = new Set<string>();
  /** In-flight hydrations keyed by `${taskRunId}:${hydrationMode}` */
  private cloudHydrationPromises = new Map<
    string,
    Promise<CloudHydrationResult | undefined>
  >();
  /** Deduplicates concurrent manifest reads when a message renders many images. */
  private cloudAttachmentManifestRequests = new Map<
    string,
    Promise<TaskRunArtifact[]>
  >();
  private idleKilledSubscription: { unsubscribe: () => void } | null = null;
  /**
   * Cached preview-config-options responses keyed by `${apiHost}::${adapter}`.
   * Shared across cloud sessions so switching model/adapter reuses the list.
   */
  private previewConfigOptionsCache = new Map<
    string,
    { promise: Promise<SessionConfigOption[]>; fetchedAt: number }
  >();
  /**
   * Initial cloud prompt text (user message + any channel CONTEXT.md block),
   * stashed by task creation keyed by taskId. The cloud sandbox takes seconds to
   * boot and echo this back, so the optimistic placeholder would otherwise show
   * the bare task description with no CONTEXT.md chip until the echo lands. Seed
   * the placeholder with this richer text instead, then drop it once consumed.
   */
  private initialCloudOptimisticPrompt = new Map<string, string>();

  constructor(private readonly d: SessionServiceDeps) {
    this.cloudRunIdleTracker = new CloudRunIdleTracker();
    this.cloudLogGapReconciler = new CloudLogGapReconciler({
      fetchLogs: (logUrl, taskRunId, minEntryCount) =>
        this.fetchSessionLogs(logUrl, taskRunId, { minEntryCount }),
      getSession: (taskRunId) => {
        const session = d.store.getSessions()[taskRunId];
        if (!session) return undefined;
        return {
          taskId: session.taskId,
          processedLineCount: session.processedLineCount ?? 0,
          logUrl: session.logUrl,
        };
      },
      commit: (taskRunId, rawEntries, logUrl, processedLineCount) =>
        this.commitReconciledCloudEvents(
          taskRunId,
          rawEntries,
          logUrl,
          processedLineCount,
        ),
      logger: d.log,
    });
    this.idleKilledSubscription = d.trpc.agent.onSessionIdleKilled.subscribe(
      undefined,
      {
        onData: (event: { taskRunId: string }) => {
          const { taskRunId } = event;
          d.log.info("Session idle-killed by main process", { taskRunId });
          this.handleIdleKill(taskRunId);
        },
        onError: (err: unknown) => {
          d.log.debug("Idle-killed subscription error", { error: err });
        },
      },
    );
  }

  /**
   * Connect to a task session.
   * Uses locking to prevent duplicate concurrent connections.
   */
  async connectToTask(params: ConnectParams): Promise<void> {
    const { task } = params;
    const taskId = task.id;
    this.taskCreationMarks.delete(taskId);
    this.localRepoPaths.set(taskId, params.repoPath);
    this.sessionLastUsedAt.set(taskId, Date.now());
    void this.evictIdleSessions(taskId);

    // Return existing connection promise if already connecting
    const existingPromise = this.connectingTasks.get(taskId);
    if (existingPromise) {
      return existingPromise;
    }

    // Check for existing connected session
    const existingSession = this.d.store.getSessionByTaskId(taskId);
    if (existingSession?.status === "connected") {
      this.d.log.info("Already connected to task", { taskId });
      return;
    }
    if (existingSession?.status === "connecting") {
      this.d.log.info("Session already in connecting state", { taskId });
      return;
    }

    // Create and store the connection promise
    const connectPromise = this.doConnect(params).finally(() => {
      this.connectingTasks.delete(taskId);
    });
    this.connectingTasks.set(taskId, connectPromise);

    return connectPromise;
  }

  private stampRunConfig(session: AgentSession, params: ConnectParams): void {
    session.adapter = params.adapter;
    session.model = params.model;
    session.executionMode = params.executionMode;
    session.reasoningLevel = params.reasoningLevel;
    if (params.initialPrompt?.length) {
      session.initialPrompt = params.initialPrompt;
    }
  }

  private async doConnect(params: ConnectParams): Promise<void> {
    const {
      task,
      repoPath,
      initialPrompt,
      executionMode,
      adapter,
      model,
      reasoningLevel,
      importedSessionId,
    } = params;
    const { id: taskId, latest_run: latestRun } = task;
    const taskTitle = task.title || task.description || "Task";

    if (latestRun?.environment === "cloud") {
      this.d.log.info("Skipping local session connect for cloud run", {
        taskId,
        taskRunId: latestRun.id,
      });
      return;
    }

    try {
      const authStatus = await this.getAuthCredentialsStatus();
      if (authStatus.kind === "restoring") {
        throw new Error("Authentication is still restoring. Please wait.");
      }
      const auth = authStatus.kind === "ready" ? authStatus.auth : null;
      const route = routeLocalConnect({
        hasAuth: auth !== null,
        latestRunId: latestRun?.id,
        latestRunLogUrl: latestRun?.log_url,
      });

      if (route.kind === "no-auth" || !auth) {
        this.d.log.error("Missing auth credentials");
        const taskRunId = latestRun?.id ?? `error-${taskId}`;
        const session = createBaseSession(taskRunId, taskId, taskTitle);
        session.status = "error";
        session.errorMessage =
          "Authentication required. Please sign in to continue.";
        this.stampRunConfig(session, params);
        this.d.store.setSession(session);
        return;
      }

      if (route.kind === "resume-existing") {
        const { taskRunId: existingRunId, logUrl } = route;
        if (!this.d.getIsOnline()) {
          this.d.log.info("Skipping connection attempt - offline", { taskId });
          const { rawEntries } = await this.fetchSessionLogs(
            logUrl,
            existingRunId,
          );
          const events = convertStoredEntriesToEvents(rawEntries);
          const session = createBaseSession(existingRunId, taskId, taskTitle);
          session.events = events;
          session.logUrl = logUrl;
          session.status = "disconnected";
          session.errorMessage = OFFLINE_SESSION_MESSAGE;
          this.d.store.setSession(session);
          return;
        }

        // Paint the log tail immediately so a big transcript is visible in tens
        // of ms; the full read + reconnect replace it with the authoritative
        // session once everything below resolves.
        const [workspaceResult, logResult] = await Promise.all([
          this.d.trpc.workspace.verify.query({ taskId }),
          this.fetchSessionLogs(logUrl, existingRunId),
          this.paintTailFirst(existingRunId, taskId, taskTitle, logUrl),
        ]);

        if (!workspaceResult.exists) {
          this.d.log.warn("Workspace no longer exists, showing error state", {
            taskId,
            missingPath: workspaceResult.missingPath,
          });
          const events = convertStoredEntriesToEvents(logResult.rawEntries);
          const session = createBaseSession(existingRunId, taskId, taskTitle);
          session.events = events;
          session.logUrl = logUrl;
          session.status = "error";
          session.errorMessage = workspaceResult.missingPath
            ? `Working directory no longer exists: ${workspaceResult.missingPath}`
            : "The working directory for this task no longer exists. Please start a new session.";
          this.d.store.setSession(session);
          return;
        }

        await this.reconnectToLocalSession(
          taskId,
          existingRunId,
          taskTitle,
          logUrl,
          repoPath,
          auth,
          logResult,
        );
      } else {
        if (!this.d.getIsOnline()) {
          this.d.log.info("Skipping connection attempt - offline", { taskId });
          const taskRunId = latestRun?.id ?? `offline-${taskId}`;
          const session = createBaseSession(taskRunId, taskId, taskTitle);
          session.status = "disconnected";
          session.errorMessage =
            "No internet connection. Connect when you're back online.";
          this.d.store.setSession(session);
          return;
        }

        await this.createNewLocalSession(
          taskId,
          taskTitle,
          repoPath,
          auth,
          initialPrompt,
          executionMode,
          adapter,
          model,
          reasoningLevel,
          importedSessionId,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.d.log.error("Failed to connect to task", { message });

      const taskRunId = latestRun?.id ?? `error-${taskId}`;
      const session = createBaseSession(taskRunId, taskId, taskTitle);
      this.stampRunConfig(session, params);
      if (latestRun?.log_url) {
        try {
          const { rawEntries } = await this.fetchSessionLogs(
            latestRun.log_url,
            latestRun.id,
          );
          session.events = convertStoredEntriesToEvents(rawEntries);
          session.logUrl = latestRun.log_url;
        } catch {
          // Ignore log fetch errors
        }
      }

      const shouldAutoRetry = this.d.getIsOnline();
      session.status = shouldAutoRetry ? "connecting" : "error";
      if (!shouldAutoRetry) {
        session.errorTitle = "Failed to connect";
        session.errorMessage = message;
      }
      this.d.store.setSession(session);

      if (!shouldAutoRetry) return;

      let lastRetryMessage = message;
      let wentOffline = false;
      let restoringWaits = 0;
      let attempt = 0;
      while (attempt < AUTO_RETRY_MAX_ATTEMPTS) {
        await new Promise((resolve) =>
          setTimeout(resolve, AUTO_RETRY_DELAY_MS),
        );
        if (!this.d.getIsOnline()) {
          this.d.log.warn("Skipping retry — device went offline", { taskId });
          wentOffline = true;
          break;
        }

        // Wait out an in-flight restore instead of spending a retry on
        // clearSessionError, which tears the connecting session down.
        if (
          restoringWaits < AUTH_RESTORE_MAX_RETRY_WAITS &&
          (await this.getAuthCredentialsStatus()).kind === "restoring"
        ) {
          restoringWaits++;
          this.d.log.info("Auth still restoring; keeping session connecting", {
            taskId,
            restoringWaits,
          });
          continue;
        }

        attempt++;
        this.d.log.warn("Auto-retrying failed connection", {
          taskId,
          attempt,
          delayMs: AUTO_RETRY_DELAY_MS,
        });
        try {
          await this.clearSessionError(taskId, repoPath);
          return;
        } catch (retryError) {
          lastRetryMessage =
            retryError instanceof Error
              ? retryError.message
              : String(retryError);
          this.d.log.error("Auto-retry via clearSessionError failed", {
            taskId,
            attempt,
            error: lastRetryMessage,
          });
        }
      }

      const currentSession = this.d.store.getSessionByTaskId(taskId);
      if (!currentSession) return;
      this.d.store.updateSession(
        currentSession.taskRunId,
        computeAutoRetryFinalState({
          wentOffline,
          lastRetryMessage,
          originalMessage: message,
        }),
      );
    }
  }

  private async reconnectToLocalSession(
    taskId: string,
    taskRunId: string,
    taskTitle: string,
    logUrl: string | undefined,
    repoPath: string,
    auth: AuthCredentials,
    prefetchedLogs?: {
      rawEntries: StoredLogEntry[];
      sessionId?: string;
      adapter?: Adapter;
    },
  ): Promise<boolean> {
    const { rawEntries, sessionId, adapter } =
      prefetchedLogs ?? (await this.fetchSessionLogs(logUrl, taskRunId));
    const events = convertStoredEntriesToEvents(rawEntries);

    const storedAdapter = this.d.adapterStore.getAdapter(taskRunId);
    const resolvedAdapter = adapter ?? storedAdapter;
    const persistedConfigOptions = this.d.getPersistedConfigOptions(taskRunId);

    const previous = this.d.store.getSessions()[taskRunId];

    const session = createBaseSession(taskRunId, taskId, taskTitle);
    // Repainting from the log must not blank a transcript we already hold:
    // fetchSessionLogs swallows read errors and returns empty, so keep the
    // previous in-memory events when the log read produced nothing.
    session.events =
      events.length === 0 && previous?.events.length ? previous.events : events;
    if (logUrl) {
      session.logUrl = logUrl;
    }
    if (persistedConfigOptions) {
      session.configOptions = persistedConfigOptions;
    }
    if (resolvedAdapter) {
      session.adapter = resolvedAdapter;
      this.d.adapterStore.setAdapter(taskRunId, resolvedAdapter);
    }

    if (previous) {
      session.optimisticItems = previous.optimisticItems;
      session.messageQueue = previous.messageQueue;
      // Keep the in-place edit hold with the queue it guards: dropping it here
      // would let the edited message auto-send in its stale, pre-edit form.
      session.editingQueuedId = previous.editingQueuedId;
      session.isPromptPending = previous.isPromptPending;
      session.promptStartedAt = previous.promptStartedAt;
      session.pausedDurationMs = previous.pausedDurationMs;
    }

    this.d.store.setSession(session);
    this.subscribeToChannel(taskRunId);

    try {
      const modeOpt = getConfigOptionByCategory(persistedConfigOptions, "mode");
      const persistedMode =
        modeOpt?.type === "select" ? modeOpt.currentValue : undefined;

      // Resumed SDK sessions don't remember the model — without this the
      // session silently falls back to the default model on every reconnect.
      const modelOpt = getConfigOptionByCategory(
        persistedConfigOptions,
        "model",
      );
      const persistedModel =
        modelOpt?.type === "select" ? modelOpt.currentValue : undefined;

      this.d.trpc.workspace.verify
        .query({ taskId })
        .then((workspaceResult) => {
          if (!workspaceResult.exists) {
            this.d.log.warn("Workspace no longer exists", {
              taskId,
              missingPath: workspaceResult.missingPath,
            });
            this.d.store.updateSession(taskRunId, {
              status: "error",
              errorMessage: workspaceResult.missingPath
                ? `Working directory no longer exists: ${workspaceResult.missingPath}`
                : "The working directory for this task no longer exists. Please start a new session.",
            });
          }
        })
        .catch((err) => {
          this.d.log.warn("Failed to verify workspace", { taskId, err });
        });

      const { customInstructions, rtkEnabledLocal, spokenNarrationEnabled } =
        this.d.settings;
      const result = await this.d.trpc.agent.reconnect.mutate({
        taskId,
        taskRunId,
        repoPath,
        rtkEnabled: rtkEnabledLocal,
        spokenNarration: spokenNarrationEnabled === true,
        apiHost: auth.apiHost,
        projectId: auth.projectId,
        logUrl,
        sessionId,
        adapter: resolvedAdapter,
        permissionMode: persistedMode,
        model: persistedModel,
        customInstructions: customInstructions || undefined,
      });

      if (result) {
        const liveConfigOptions = result.configOptions as
          | SessionConfigOption[]
          | undefined;

        // Only restore persisted options the resumed session still supports:
        // it must advertise an option with the same id and still offer the
        // persisted value (see isPersistedOptionSupported). Without live
        // options (e.g. after session compaction) we can't confirm support, so
        // we restore nothing rather than push a value the agent may reject —
        // the same failure this guard exists to prevent.
        const restorableConfigOptions =
          liveConfigOptions && persistedConfigOptions
            ? persistedConfigOptions.filter((persistedOption) =>
                isPersistedOptionSupported(persistedOption, liveConfigOptions),
              )
            : [];

        // Merge only the restorable persisted values into the live options so
        // the stored and displayed config never shows a setting the resumed
        // agent rejected. Fall back to persisted options for display when the
        // agent returns none (nothing is pushed to the server in that case).
        let configOptions: SessionConfigOption[] | undefined;
        if (liveConfigOptions) {
          configOptions = restorableConfigOptions.length
            ? mergeConfigOptions(liveConfigOptions, restorableConfigOptions)
            : liveConfigOptions;
        } else {
          configOptions = persistedConfigOptions ?? undefined;
        }

        this.d.store.updateSession(taskRunId, {
          status: "connected",
          configOptions,
          steering: readSteering(result),
        });

        // Persist the merged config options
        if (configOptions) {
          this.d.setPersistedConfigOptions(taskRunId, configOptions);
        }

        // Restore supported persisted config options to server in parallel
        if (restorableConfigOptions.length) {
          await Promise.all(
            restorableConfigOptions.map((opt) =>
              this.d.trpc.agent.setConfigOption
                .mutate({
                  sessionId: taskRunId,
                  configId: opt.id,
                  value: String(opt.currentValue),
                })
                .catch((error) => {
                  this.d.log.warn(
                    "Failed to restore persisted config option after reconnect",
                    {
                      taskId,
                      configId: opt.id,
                      error,
                    },
                  );
                }),
            ),
          );
        }
        return true;
      } else {
        this.d.log.warn("Reconnect returned null", { taskId, taskRunId });
        this.setErrorSession(
          taskId,
          taskRunId,
          taskTitle,
          "Session could not be resumed. Please retry or start a new session.",
        );
        return false;
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      this.d.log.warn("Reconnect failed", { taskId, error: errorMessage });
      this.setErrorSession(
        taskId,
        taskRunId,
        taskTitle,
        errorMessage ||
          "Failed to reconnect. Please retry or start a new session.",
      );
      return false;
    }
  }

  private async teardownSession(
    taskRunId: string,
    opts?: { preserveResumeState?: boolean },
  ): Promise<void> {
    const session = this.getSessionByRunId(taskRunId);

    try {
      await this.d.trpc.agent.cancel.mutate({ sessionId: taskRunId });
    } catch (error) {
      this.d.log.debug(
        "Cancel during teardown failed (session may already be gone)",
        {
          taskRunId,
          error: error instanceof Error ? error.message : String(error),
        },
      );
    }

    this.unsubscribeFromChannel(taskRunId);
    this.cancelEventEviction(taskRunId);
    this.evictedRunIds.delete(taskRunId);
    this.d.store.removeSession(taskRunId);
    this.cloudRunIdleTracker.delete(taskRunId);
    this.cloudLogGapReconciler.forgetDeficiency(taskRunId);
    if (session) {
      this.localRepoPaths.delete(session.taskId);
      this.localRecoveryAttempts.delete(session.taskId);
      this.sessionLastUsedAt.delete(session.taskId);
    }
    if (!opts?.preserveResumeState) {
      // Reconnect restores the model and permission mode from these; only a
      // permanent disconnect (archive, delete, fresh session) may drop them.
      this.d.adapterStore.removeAdapter(taskRunId);
      this.d.removePersistedConfigOptions(taskRunId);
    }
  }

  /**
   * Handle an idle-kill from the main process without destroying session state.
   * The main process already cleaned up the agent, so we only need to
   * unsubscribe from the channel and mark the session as errored.
   * Preserves events, logUrl, configOptions and adapter so that Retry
   * can reconnect with full context via resumeSession.
   */
  private handleIdleKill(taskRunId: string): void {
    this.unsubscribeFromChannel(taskRunId);
    this.d.store.updateSession(taskRunId, {
      status: "error",
      errorMessage: "Session disconnected due to inactivity. Reconnecting…",
      isPromptPending: false,
      isCompacting: false,
      promptStartedAt: null,
      idleKilled: true,
    });
  }

  private setErrorSession(
    taskId: string,
    taskRunId: string,
    taskTitle: string,
    errorMessage: string,
    errorTitle?: string,
  ): void {
    // Preserve events and logUrl from the existing session so the
    // retry / reset flows can re-hydrate without a fresh log fetch.
    // Note: the error overlay is opaque, so these events aren't visible
    // to the user — they're carried forward for the next reconnect attempt.
    const existing = this.d.store.getSessionByTaskId(taskId);
    const session = createBaseSession(taskRunId, taskId, taskTitle);
    session.status = "error";
    session.errorTitle = errorTitle;
    session.errorMessage = errorMessage;
    if (existing?.events?.length) {
      session.events = existing.events;
    }
    if (existing?.logUrl) {
      session.logUrl = existing.logUrl;
    }
    if (existing?.initialPrompt?.length) {
      session.initialPrompt = existing.initialPrompt;
    }
    this.d.store.setSession(session);
  }

  private async tryAutoRecoverLocalSession(
    taskId: string,
    taskRunId: string,
    reason: string,
  ): Promise<boolean> {
    const existingRecovery = this.localRecoveryAttempts.get(taskId);
    if (existingRecovery) {
      return existingRecovery;
    }

    const recoveryPromise = this.runAutoRecoverLocalSession(
      taskId,
      taskRunId,
      reason,
    ).finally(() => {
      this.localRecoveryAttempts.delete(taskId);
    });

    this.localRecoveryAttempts.set(taskId, recoveryPromise);
    return recoveryPromise;
  }

  private async runAutoRecoverLocalSession(
    taskId: string,
    taskRunId: string,
    reason: string,
  ): Promise<boolean> {
    const repoPath = this.localRepoPaths.get(taskId);
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!repoPath || !session || session.isCloud) {
      return false;
    }

    this.d.log.warn("Attempting automatic local session recovery", {
      taskId,
      taskRunId,
      reason,
    });

    this.d.store.updateSession(taskRunId, {
      status: "disconnected",
      errorTitle: undefined,
      errorMessage: LOCAL_SESSION_RECOVERY_MESSAGE,
      isPromptPending: false,
      isCompacting: false,
      promptStartedAt: null,
    });

    for (
      let attempt = 0;
      attempt < LOCAL_SESSION_RECONNECT_ATTEMPTS;
      attempt++
    ) {
      const currentSession = this.d.store.getSessionByTaskId(taskId);
      if (!currentSession || currentSession.taskRunId !== taskRunId) {
        return false;
      }

      if (attempt > 0) {
        const delay = getBackoffDelay(
          attempt - 1,
          LOCAL_SESSION_RECONNECT_BACKOFF,
        );
        await new Promise((resolve) => setTimeout(resolve, delay));
      }

      const recovered = await this.reconnectInPlace(taskId, repoPath);
      if (recovered) {
        this.d.log.info("Automatic local session recovery succeeded", {
          taskId,
          taskRunId,
          attempt: attempt + 1,
        });
        return true;
      }
    }

    const latestSession = this.d.store.getSessionByTaskId(taskId);
    if (latestSession?.taskRunId === taskRunId) {
      this.setErrorSession(
        taskId,
        taskRunId,
        latestSession.taskTitle,
        LOCAL_SESSION_RECOVERY_FAILED_MESSAGE,
        "Connection lost",
      );
    }

    this.d.log.warn("Automatic local session recovery exhausted", {
      taskId,
      taskRunId,
    });

    return false;
  }

  private startAutoRecoverLocalSession(
    taskId: string,
    taskRunId: string,
    taskTitle: string,
    reason: string,
    fallbackMessage: string,
  ): void {
    void this.tryAutoRecoverLocalSession(taskId, taskRunId, reason).then(
      (recovered) => {
        if (recovered) {
          return;
        }

        const latestSession = this.d.store.getSessionByTaskId(taskId);
        if (!latestSession || latestSession.taskRunId !== taskRunId) {
          return;
        }

        if (latestSession.status !== "error") {
          this.setErrorSession(
            taskId,
            taskRunId,
            taskTitle,
            fallbackMessage,
            "Connection lost",
          );
        }
      },
    );
  }

  private async createNewLocalSession(
    taskId: string,
    taskTitle: string,
    repoPath: string,
    auth: AuthCredentials,
    initialPrompt?: ContentBlock[],
    executionMode?: ExecutionMode,
    adapter?: Adapter,
    model?: string,
    reasoningLevel?: string,
    importedSessionId?: string,
  ): Promise<void> {
    const { client } = auth;
    if (!client) {
      throw new Error("Unable to reach server. Please check your connection.");
    }

    const taskRun = await client.createTaskRun(taskId);
    if (!taskRun?.id) {
      throw new Error("Failed to create task run. Please try again.");
    }

    const {
      customInstructions: startCustomInstructions,
      rtkEnabledLocal,
      spokenNarrationEnabled,
    } = this.d.settings;
    const preferredModel = model ?? this.d.DEFAULT_GATEWAY_MODEL;
    const result = await this.d.trpc.agent.start.mutate({
      taskId,
      taskRunId: taskRun.id,
      repoPath,
      apiHost: auth.apiHost,
      projectId: auth.projectId,
      permissionMode: executionMode,
      adapter,
      customInstructions: startCustomInstructions || undefined,
      rtkEnabled: rtkEnabledLocal,
      spokenNarration: spokenNarrationEnabled === true,
      effort: effortLevelSchema.safeParse(reasoningLevel).success
        ? (reasoningLevel as EffortLevel)
        : undefined,
      model: preferredModel,
      importedSessionId,
    });

    const session = createBaseSession(taskRun.id, taskId, taskTitle);
    session.channel = result.channel;
    session.status = "connected";
    session.adapter = adapter;
    session.model = model;
    session.executionMode = executionMode;
    session.reasoningLevel = reasoningLevel;

    // An imported CLI session had its history replayed during agent.start;
    // the replay is already in the local run log, so load it for the UI.
    if (importedSessionId) {
      try {
        const { rawEntries } = await this.fetchSessionLogs(
          undefined,
          taskRun.id,
        );
        session.events = convertStoredEntriesToEvents(rawEntries);
      } catch {
        this.d.log.warn(
          "Failed to load replayed history for imported session",
          {
            taskRunId: taskRun.id,
          },
        );
      }
    }
    const configOptions = result.configOptions as
      | SessionConfigOption[]
      | undefined;
    session.configOptions = configOptions;
    session.steering = readSteering(result);

    // Persist the config options
    if (configOptions) {
      this.d.setPersistedConfigOptions(taskRun.id, configOptions);
    }

    // Persist the adapter so reconnects resume with the same one.
    if (adapter) {
      this.d.adapterStore.setAdapter(taskRun.id, adapter);
    }

    // Store the initial prompt on the session so retry/reset flows can
    // re-send it if the session errors after this point (e.g. subscription
    // error, agent crash, or prompt failure).
    if (initialPrompt?.length) {
      session.initialPrompt = initialPrompt;
    }

    this.d.store.setSession(session);
    this.subscribeToChannel(taskRun.id);

    this.d.track(ANALYTICS_EVENTS.TASK_RUN_STARTED, {
      task_id: taskId,
      execution_type: "local",
      initial_mode: executionMode,
      adapter,
    });

    if (initialPrompt?.length) {
      await this.sendPrompt(taskId, initialPrompt);
    }
  }

  async loadLogsOnly(params: {
    taskId: string;
    taskRunId: string;
    taskTitle: string;
    logUrl: string;
  }): Promise<void> {
    const { taskId, taskRunId, taskTitle, logUrl } = params;
    const existing = this.d.store.getSessionByTaskId(taskId);
    if (existing && existing.events.length > 0) return;

    const { rawEntries } = await this.fetchSessionLogs(logUrl, taskRunId);
    const events = convertStoredEntriesToEvents(rawEntries);
    const session = createBaseSession(taskRunId, taskId, taskTitle);
    session.events = events;
    session.logUrl = logUrl;
    session.status = "disconnected";
    this.d.store.setSession(session);
  }

  async disconnectFromTask(taskId: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;

    await this.teardownSession(session.taskRunId);
  }

  registerMountedTask(taskId: string): () => void {
    this.mountedTaskCounts.set(
      taskId,
      (this.mountedTaskCounts.get(taskId) ?? 0) + 1,
    );
    this.sessionLastUsedAt.set(taskId, Date.now());
    return () => {
      const count = this.mountedTaskCounts.get(taskId) ?? 0;
      if (count <= 1) {
        this.mountedTaskCounts.delete(taskId);
      } else {
        this.mountedTaskCounts.set(taskId, count - 1);
      }
      this.sessionLastUsedAt.set(taskId, Date.now());
    };
  }

  private async evictIdleSessions(activeTaskId: string): Promise<void> {
    const toEvict = selectSessionsToEvict({
      sessions: Object.values(this.d.store.getSessions()),
      activeTaskId,
      protectedTaskIds: new Set(this.mountedTaskCounts.keys()),
      lastUsedAt: (session) =>
        this.sessionLastUsedAt.get(session.taskId) ?? session.startedAt,
    });

    for (const session of toEvict) {
      this.d.log.info("Evicting idle session to bound memory", {
        taskId: session.taskId,
        taskRunId: session.taskRunId,
      });
      this.sessionLastUsedAt.delete(session.taskId);
      try {
        await this.teardownSession(session.taskRunId, {
          preserveResumeState: true,
        });
      } catch (error) {
        this.d.log.error("Failed to evict idle session", {
          taskId: session.taskId,
          error,
        });
      }
    }
  }

  // --- Subscription Management ---

  /** Streamed events awaiting their frame flush, keyed by taskRunId. Order
   * within a taskRunId is preserved; taskRunIds are independent. */
  private pendingSessionEvents = new Map<string, AcpMessage[]>();
  private sessionEventFlushHandle: ReturnType<typeof setTimeout> | null = null;

  private enqueueSessionEvent(taskRunId: string, acpMsg: AcpMessage): void {
    const buffered = this.pendingSessionEvents.get(taskRunId);
    if (buffered) {
      buffered.push(acpMsg);
    } else {
      this.pendingSessionEvents.set(taskRunId, [acpMsg]);
    }
    if (this.sessionEventFlushHandle === null) {
      this.sessionEventFlushHandle = setTimeout(() => {
        this.sessionEventFlushHandle = null;
        this.flushSessionEvents();
      }, SESSION_EVENT_FLUSH_MS);
    }
  }

  private flushSessionEvents(): void {
    if (this.pendingSessionEvents.size === 0) return;
    const batches = this.pendingSessionEvents;
    this.pendingSessionEvents = new Map();
    for (const [taskRunId, events] of batches) {
      for (const acpMsg of events) {
        this.handleSessionEvent(taskRunId, acpMsg);
      }
    }
  }

  /** Drain one task's buffer immediately, so a reader (permission handling,
   * teardown) never sees a transcript missing already-received events. */
  private flushSessionEventsForTask(taskRunId: string): void {
    const events = this.pendingSessionEvents.get(taskRunId);
    if (!events) return;
    this.pendingSessionEvents.delete(taskRunId);
    for (const acpMsg of events) {
      this.handleSessionEvent(taskRunId, acpMsg);
    }
  }

  // --- Transcript residency (memory eviction) ---

  /** taskRunIds whose transcript was freed and must be reloaded on next view. */
  private evictedRunIds = new Set<string>();
  private eventEvictionTimers = new Map<
    string,
    ReturnType<typeof setTimeout>
  >();

  /**
   * Called when a task's transcript becomes visible. Cancels any pending
   * eviction and, if the transcript was freed while backgrounded, reloads it
   * from disk — but only if a reconnect hasn't already refilled it.
   */
  async ensureEventsLoaded(taskId: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;
    const { taskRunId } = session;
    this.cancelEventEviction(taskRunId);
    if (!this.evictedRunIds.has(taskRunId)) return;

    try {
      if (session.events.length === 0) {
        const { rawEntries, totalLineCount } = await this.fetchSessionLogs(
          session.logUrl,
          taskRunId,
        );
        // A reconnect may have refilled events while we awaited the log read;
        // only restore if the transcript is still empty for the same run.
        const fresh = this.d.store.getSessionByTaskId(taskId);
        if (
          fresh?.taskRunId === taskRunId &&
          fresh.events.length === 0 &&
          rawEntries.length > 0
        ) {
          this.d.store.restoreEvents(
            taskRunId,
            convertStoredEntriesToEvents(rawEntries),
            totalLineCount,
          );
        }
      }
      // Clear the evicted flag only once the transcript is populated — restored
      // here, or refilled by a reconnect. An empty read leaves the run evicted so
      // a later visit retries: fetchSessionLogs swallows read errors and returns
      // empty rather than throwing, so a transient failure would otherwise strand
      // the transcript empty permanently.
      if ((this.d.store.getSessionByTaskId(taskId)?.events.length ?? 0) > 0) {
        this.evictedRunIds.delete(taskRunId);
      }
    } catch (error) {
      this.d.log.warn("Failed to rehydrate evicted session transcript", {
        taskId,
        error,
      });
    }
  }

  /**
   * Called when a task's transcript stops being visible. Schedules its
   * transcript to be freed after a grace period, if it's still a settled,
   * disconnected background session by then.
   */
  scheduleEventEviction(taskId: string): void {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;
    const { taskRunId } = session;
    if (this.eventEvictionTimers.has(taskRunId)) return;

    const timer = setTimeout(() => {
      this.eventEvictionTimers.delete(taskRunId);
      const current = this.d.store.getSessions()[taskRunId];
      if (
        !current ||
        current.status !== "disconnected" ||
        current.isPromptPending ||
        current.events.length === 0
      ) {
        return;
      }
      this.evictedRunIds.add(taskRunId);
      this.d.store.evictEvents(taskRunId);
    }, SESSION_EVENT_EVICT_GRACE_MS);
    this.eventEvictionTimers.set(taskRunId, timer);
  }

  private cancelEventEviction(taskRunId: string): void {
    const timer = this.eventEvictionTimers.get(taskRunId);
    if (timer !== undefined) {
      clearTimeout(timer);
      this.eventEvictionTimers.delete(taskRunId);
    }
  }

  private subscribeToChannel(taskRunId: string): void {
    if (this.subscriptions.has(taskRunId)) {
      return;
    }

    const eventSubscription = this.d.trpc.agent.onSessionEvent.subscribe(
      { taskRunId },
      {
        onData: (payload: unknown) => {
          this.enqueueSessionEvent(taskRunId, payload as AcpMessage);
        },
        onError: (err) => {
          this.d.log.error("Session subscription error", {
            taskRunId,
            error: err,
          });
          const session = this.getSessionByRunId(taskRunId);
          if (!session || session.isCloud) {
            this.d.store.updateSession(taskRunId, {
              status: "error",
              errorMessage:
                "Lost connection to the agent. Please restart the task.",
            });
            return;
          }

          this.startAutoRecoverLocalSession(
            session.taskId,
            taskRunId,
            session.taskTitle,
            "subscription_error",
            "Lost connection to the agent. Please retry or start a new session.",
          );
        },
      },
    );

    const permissionSubscription =
      this.d.trpc.agent.onPermissionRequest.subscribe(
        { taskRunId },
        {
          onData: async (payload) => {
            this.handlePermissionRequest(taskRunId, payload);
          },
          onError: (err) => {
            this.d.log.error("Permission subscription error", {
              taskRunId,
              error: err,
            });
          },
        },
      );

    this.subscriptions.set(taskRunId, {
      event: eventSubscription,
      permission: permissionSubscription,
    });
  }

  private unsubscribeFromChannel(taskRunId: string): void {
    // Apply anything still buffered before we stop listening, so a closing
    // channel doesn't drop its final events.
    this.flushSessionEventsForTask(taskRunId);
    const subscription = this.subscriptions.get(taskRunId);
    subscription?.event.unsubscribe();
    subscription?.permission?.unsubscribe();
    this.subscriptions.delete(taskRunId);
    this.liveTurnContent.delete(taskRunId);
    this.agentSpokeAt.delete(taskRunId);
    // Drop any speak calls still mid-stream for this run (never reached a
    // terminal status, so they were never enqueued or deleted above).
    this.speakCalls.delete(taskRunId);
  }

  /**
   * Reset all service state and clean up subscriptions.
   * Called on logout or app reset.
   */
  reset(): void {
    this.d.log.info("Resetting session service", {
      subscriptionCount: this.subscriptions.size,
      connectingCount: this.connectingTasks.size,
      cloudWatcherCount: this.cloudTaskWatchers.size,
    });

    // Unsubscribe from all active subscriptions
    for (const taskRunId of this.subscriptions.keys()) {
      this.unsubscribeFromChannel(taskRunId);
    }

    // Clean up all cloud task watchers
    for (const taskId of [...this.cloudTaskWatchers.keys()]) {
      this.stopCloudTaskWatch(taskId);
    }

    if (this.sessionEventFlushHandle !== null) {
      clearTimeout(this.sessionEventFlushHandle);
      this.sessionEventFlushHandle = null;
    }
    this.pendingSessionEvents.clear();
    for (const timer of this.eventEvictionTimers.values()) clearTimeout(timer);
    this.eventEvictionTimers.clear();
    this.evictedRunIds.clear();
    this.connectingTasks.clear();
    this.localRepoPaths.clear();
    this.localRecoveryAttempts.clear();
    this.reconcileSkipLogged.clear();
    this.taskCreationMarks.clear();
    this.sessionLastUsedAt.clear();
    this.cloudPermissionRequestIds.clear();
    this.liveTurnContent.clear();
    this.speakCalls.clear();
    this.agentSpokeAt.clear();
    this.cloudLogGapReconciler.clear();
    this.dispatchingCloudQueues.clear();
    this.scheduledCloudQueueFlushes.clear();
    this.cloudRunIdleTracker.clear();
    this.idleKilledSubscription?.unsubscribe();
    this.idleKilledSubscription = null;
  }

  /**
   * A steer message rides on `session/prompt` with `_meta.steer`. It is folded
   * into the running turn, so its request must not participate in turn-state
   * bookkeeping (currentPromptId / isPromptPending) or the live turn would be
   * cut short. Its response carries a foreign request id, so the currentPromptId
   * guard ignores it without needing a marker here.
   */
  private isSteerMessage(msg: AcpMessage["message"]): boolean {
    if (isJsonRpcRequest(msg) && msg.method === "session/prompt") {
      const params = msg.params as { _meta?: { steer?: boolean } } | undefined;
      return params?._meta?.steer === true;
    }
    return false;
  }

  private finalizeTurnContent(
    taskRunId: string,
    trigger: "stop_reason" | "turn_complete",
    endedAtTs: number,
  ): void {
    const tally = this.liveTurnContent.get(taskRunId);
    if (!tally) return;
    this.liveTurnContent.delete(taskRunId);
    const session = this.d.store.getSessions()[taskRunId];
    const payload = {
      taskRunId,
      taskId: session?.taskId,
      isCloud: session?.isCloud ?? false,
      trigger,
      agentTextChunks: tally.agentTextChunks,
      agentOutputEvents: tally.agentOutputEvents,
      durationMs: Math.max(0, endedAtTs - tally.startedAtTs),
    };
    if (tally.agentTextChunks === 0 && tally.agentOutputEvents === 0) {
      this.d.log.warn("Turn completed with no agent output", payload);
    } else {
      this.d.log.debug("Turn completed", payload);
    }
  }

  private updatePromptStateFromEvents(
    taskRunId: string,
    events: AcpMessage[],
    { isLive = false }: { isLive?: boolean } = {},
  ): void {
    for (const acpMsg of events) {
      const msg = acpMsg.message;
      // A steer is injected into the running turn, not a turn of its own. Skip
      // its request so it never claims currentPromptId. Otherwise the steer's
      // instant response would clear the live turn's pending state.
      if (this.isSteerMessage(msg)) {
        continue;
      }
      const turnTally = isLive
        ? this.liveTurnContent.get(taskRunId)
        : undefined;
      if (turnTally) {
        const kind = classifyTurnEventKind(msg);
        if (kind === "text") turnTally.agentTextChunks += 1;
        else if (kind === "output") turnTally.agentOutputEvents += 1;
      }
      if (isJsonRpcRequest(msg) && msg.method === "session/prompt") {
        this.d.store.updateSession(taskRunId, {
          isPromptPending: true,
          promptStartedAt: acpMsg.ts,
          pausedDurationMs: 0,
          currentPromptId: msg.id,
        });
        if (isLive) {
          this.liveTurnContent.set(taskRunId, {
            startedAtTs: acpMsg.ts,
            agentTextChunks: 0,
            agentOutputEvents: 0,
          });
        }
        const promptSession = this.d.store.getSessions()[taskRunId];
        if (promptSession?.isCloud) {
          this.cloudRunIdleTracker.markBusy(promptSession);
          if (promptSession.agentIdleForRunId) {
            this.d.store.updateSession(taskRunId, {
              agentIdleForRunId: undefined,
            });
          }
        }
      }
      if (
        "id" in msg &&
        "result" in msg &&
        typeof msg.result === "object" &&
        msg.result !== null &&
        "stopReason" in msg.result
      ) {
        // Only clear pending state if this response matches the currently
        // in-flight prompt. A late response from a previously cancelled turn
        // must not be allowed to mark a newer turn as done.
        const session = this.d.store.getSessions()[taskRunId];
        if (session && session.currentPromptId !== msg.id) {
          continue;
        }
        if (session?.isCloud) {
          // Cloud logs carry both this response and `_posthog/turn_complete`,
          // in either order (they race in the agent's log stream). Only
          // turn_complete may disarm the turn; disarming here would make the
          // completion notification fire or vanish based on log line order.
          this.d.store.updateSession(taskRunId, {
            isPromptPending: false,
          });
          continue;
        }
        this.d.store.updateSession(taskRunId, {
          isPromptPending: false,
          promptStartedAt: null,
          currentPromptId: null,
        });
        if (isLive) {
          this.finalizeTurnContent(taskRunId, "stop_reason", acpMsg.ts);
        }
      }
      if (isTurnCompleteEvent(acpMsg)) {
        // Local sessions use the JSON-RPC response as the canonical turn-done
        // signal; turn_complete is the cloud one, so only cloud disarms here.
        const session = this.getSessionByRunId(taskRunId);
        if (session?.isCloud) {
          const completedActiveTurn =
            session.currentPromptId !== null &&
            session.currentPromptId !== undefined;
          const stopReason =
            (msg as { params?: { stopReason?: string } }).params?.stopReason ??
            "end_turn";
          const turnStartedAtTs =
            this.liveTurnContent.get(taskRunId)?.startedAtTs ??
            session.promptStartedAt;
          this.d.store.updateSession(taskRunId, {
            isPromptPending: false,
            promptStartedAt: null,
            currentPromptId: null,
          });
          if (isLive) {
            // Queued messages will start a new turn — suppress the "done" notification in that case.
            if (
              completedActiveTurn &&
              stopReason === "end_turn" &&
              session.messageQueue.length === 0
            ) {
              this.d.notifyPromptComplete(
                session.taskTitle,
                stopReason,
                session.taskId,
                turnStartedAtTs ? acpMsg.ts - turnStartedAtTs : undefined,
              );
              this.speakDeterministic(taskRunId, session, "done");
            }
            this.d.taskViewedApi.markActivity(session.taskId);
            this.finalizeTurnContent(taskRunId, "turn_complete", acpMsg.ts);
          }
        }
      }
      // Lifecycle handshake from the agent — flip status to "connected"
      // so the UI can release the queue-while-not-ready guard. This is
      // the explicit "agent is up and accepting user messages" signal,
      // emitted by `agent-server.ts` once the ACP session is fully
      // wired. We deliberately do NOT drain the queue here: the agent
      // is about to start `sendInitialTaskMessage` (or `sendResumeMessage`),
      // and dispatching a queued user_message right now would race with
      // its `clientConnection.prompt()` and one of the prompts would end
      // up cancelled. The `turn_complete` handler below drains once the
      // agent's initial / resume turn is actually finished.
      if (
        "method" in msg &&
        isNotification(msg.method, POSTHOG_NOTIFICATIONS.RUN_STARTED)
      ) {
        const session = this.d.store.getSessions()[taskRunId];
        const params = (
          msg as {
            params?: { agentVersion?: unknown; steering?: unknown };
          }
        ).params;
        const agentVersion =
          typeof params?.agentVersion === "string"
            ? params.agentVersion
            : undefined;
        const updates: Partial<AgentSession> = {};
        if (agentVersion && session?.agentVersion !== agentVersion) {
          updates.agentVersion = agentVersion;
        }
        if (
          typeof params?.steering === "string" &&
          session?.steering !== params.steering
        ) {
          updates.steering = params.steering;
        }
        if (session?.isCloud && session.status !== "connected") {
          updates.status = "connected";
        }
        if (Object.keys(updates).length > 0) {
          this.d.store.updateSession(taskRunId, updates);
        }
      }
      // Canonical "turn boundary" — flush any queued cloud messages now
      // that the agent is idle and accepting the next prompt.
      if (
        "method" in msg &&
        isNotification(msg.method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE)
      ) {
        const session = this.d.store.getSessions()[taskRunId];
        if (session?.isCloud) {
          // Backward compat: treat turn_complete as an implicit run_started
          // for agents that predate the run_started notification. The turn
          // finished, so the agent is idle for this run, lets a later
          // transport drop recover readiness.
          const updates: Partial<AgentSession> = {};
          if (session.status !== "connected") {
            updates.status = "connected";
          }
          if (session.agentIdleForRunId !== taskRunId) {
            updates.agentIdleForRunId = taskRunId;
          }
          if (Object.keys(updates).length > 0) {
            this.d.store.updateSession(taskRunId, updates);
          }
          this.cloudRunIdleTracker.markIdle(session);
          if (session.messageQueue.length > 0) {
            this.scheduleCloudQueueFlush(session.taskId, "turn_complete");
          }
        }
      }
    }
  }

  /**
   * Deterministic backstop for the two moments the user must not miss. Fired
   * from the turn-complete and permission events (which happen every time),
   * unless the agent already narrated that same moment this turn via the speak
   * tool — in which case its expressive line stands. Routes through the same
   * speech channel (focus + settings gating + serialized queue).
   */
  private speakDeterministic(
    taskRunId: string,
    session: {
      taskTitle: string;
      taskId: string;
      promptStartedAt: number | null;
    },
    kind: "done" | "needs_input",
  ): void {
    const turnStart = session.promptStartedAt ?? 0;
    const spokeAt = this.agentSpokeAt.get(taskRunId)?.[kind] ?? 0;
    if (turnStart > 0 && spokeAt >= turnStart) return; // agent already voiced it
    // Deterministic backstop stays plain — no "Hey <name>," greeting.
    this.d.enqueueSpeech({
      text: kind === "done" ? "finished" : "needs your input",
      taskTitle: session.taskTitle,
      taskId: session.taskId,
      kind,
      source: "backstop",
      addressByName: false,
    });
  }

  private handleSessionEvent(taskRunId: string, acpMsg: AcpMessage): void {
    const session = this.d.store.getSessions()[taskRunId];
    if (!session) return;

    const isUserPromptEcho =
      isJsonRpcRequest(acpMsg.message) &&
      acpMsg.message.method === "session/prompt";

    // Once the agent starts responding, clear initialPrompt so that
    // retry reconnects to this session instead of creating a new one.
    if (!isUserPromptEcho && session.initialPrompt?.length) {
      this.d.store.updateSession(taskRunId, {
        initialPrompt: undefined,
      });
    }

    if (isUserPromptEcho && !this.isSteerMessage(acpMsg.message)) {
      this.d.store.replaceOptimisticWithEvent(taskRunId, acpMsg);
    } else {
      this.d.store.appendEvents(taskRunId, [acpMsg]);
    }
    const turnStartedAtTs =
      this.liveTurnContent.get(taskRunId)?.startedAtTs ??
      session.promptStartedAt;
    this.updatePromptStateFromEvents(taskRunId, [acpMsg], { isLive: true });

    const msg = acpMsg.message;

    if (
      "id" in msg &&
      "result" in msg &&
      typeof msg.result === "object" &&
      msg.result !== null &&
      "stopReason" in msg.result
    ) {
      // Ignore responses that don't match the currently in-flight prompt id.
      // A late response from a cancelled prior turn must not drain the queue
      // or fire the "prompt complete" notification for the newer turn.
      // We check against `session` (captured at the top of this function, pre-update),
      // because updatePromptStateFromEvents above already cleared currentPromptId
      // for a valid match — re-reading from the store would lose the distinction
      // between "valid match just cleared" and "no turn was in flight".
      if (session.currentPromptId !== msg.id) {
        return;
      }

      const stopReason = (msg.result as { stopReason?: string }).stopReason;
      // A cancelled turn is an explicit stop: auto-firing queued messages
      // right after would restart the agent the user just halted.
      const hasSendableMessages =
        stopReason === "cancelled"
          ? false
          : this.drainQueuedMessages(taskRunId, session);

      // Only notify when nothing is sendable - queued messages start a new turn
      if (stopReason && !hasSendableMessages) {
        this.d.notifyPromptComplete(
          session.taskTitle,
          stopReason,
          session.taskId,
          turnStartedAtTs ? acpMsg.ts - turnStartedAtTs : undefined,
        );
        if (stopReason === "end_turn") {
          this.speakDeterministic(taskRunId, session, "done");
        }
      }

      this.d.taskViewedApi.markActivity(session.taskId);
    }

    if ("method" in msg && msg.method === "session/update" && "params" in msg) {
      const params = msg.params as {
        update?: {
          sessionUpdate?: string;
          configOptions?: SessionConfigOption[];
        };
      };

      // Handle config option updates (replaces current_mode_update)
      if (
        params?.update?.sessionUpdate === "config_option_update" &&
        params.update.configOptions
      ) {
        const configOptions = params.update.configOptions;
        this.d.store.updateSession(taskRunId, {
          configOptions,
        });
        // Persist the updated config options
        this.d.setPersistedConfigOptions(taskRunId, configOptions);
        this.d.log.info("Session config options updated", { taskRunId });
      }

      // Spoken narration: the agent's `speak` tool call surfaces here. The
      // initial tool_call names the tool but arrives with empty args; the
      // assembled { text, kind } stream in on later tool_call_updates with the
      // same toolCallId. So we remember speak toolCallIds, accumulate the latest
      // args, and enqueue once the call completes (with the full text).
      if (
        params?.update?.sessionUpdate === "tool_call" ||
        params?.update?.sessionUpdate === "tool_call_update"
      ) {
        const update = params.update as {
          toolCallId?: string;
          status?: string;
          _meta?: {
            claudeCode?: { toolName?: string; parentToolCallId?: string };
          };
          rawInput?: { text?: unknown; kind?: unknown };
        };
        const id = update.toolCallId;
        if (id) {
          const speakCalls = this.speakCalls.get(taskRunId);
          // Only the top-level agent narrates. A `speak` from a sub-agent
          // (spawned via the Task tool) carries a parentToolCallId; ignoring
          // those prevents several sub-agents talking over each other.
          if (
            update._meta?.claudeCode?.toolName === SPEAK_TOOL_QUALIFIED_NAME &&
            !update._meta.claudeCode.parentToolCallId &&
            !speakCalls?.has(id)
          ) {
            const calls = speakCalls ?? new Map();
            calls.set(id, null);
            this.speakCalls.set(taskRunId, calls);
          }
          const calls = this.speakCalls.get(taskRunId);
          if (calls?.has(id)) {
            // Accumulate the latest args — text grows across streamed updates.
            const text = update.rawInput?.text;
            if (typeof text === "string" && text.trim().length > 0) {
              const rawKind = update.rawInput?.kind;
              const kind: SpeechKind =
                rawKind === "needs_input" ||
                rawKind === "done" ||
                rawKind === "progress"
                  ? rawKind
                  : "progress";
              calls.set(id, { text, kind });
            }
            // Speak only once the call is complete (full text). Deleting the
            // entry both frees it and dedupes any later terminal event.
            const pending = calls.get(id);
            if (isTerminalStatus(update.status) && pending) {
              calls.delete(id);
              if (calls.size === 0) this.speakCalls.delete(taskRunId);
              if (pending.kind !== "progress") {
                const spoke = this.agentSpokeAt.get(taskRunId) ?? {
                  needs_input: 0,
                  done: 0,
                };
                spoke[pending.kind] = acpMsg.ts;
                this.agentSpokeAt.set(taskRunId, spoke);
              }
              this.d.enqueueSpeech({
                text: pending.text,
                taskTitle: session.taskTitle,
                taskId: session.taskId,
                kind: pending.kind,
                source: "agent",
                // Agent-authored line: allowed to address the user by name.
                addressByName: true,
              });
            }
          }
        }
      }

      // Handle context usage updates
      if (params?.update?.sessionUpdate === "usage_update") {
        const update = params.update as {
          used?: number;
          size?: number;
        };
        if (
          typeof update.used === "number" &&
          typeof update.size === "number"
        ) {
          this.d.store.updateSession(taskRunId, {
            contextUsed: update.used,
            contextSize: update.size,
          });
        }
      }
    }

    // Handle SDK_SESSION notifications for adapter info
    if (
      "method" in msg &&
      isNotification(msg.method, POSTHOG_NOTIFICATIONS.SDK_SESSION) &&
      "params" in msg
    ) {
      const params = msg.params as {
        adapter?: Adapter;
      };
      if (params?.adapter) {
        this.d.store.updateSession(taskRunId, {
          adapter: params.adapter,
        });
        this.d.adapterStore.setAdapter(taskRunId, params.adapter);
      }
    }

    if (
      "method" in msg &&
      "params" in msg &&
      isNotification(msg.method, POSTHOG_NOTIFICATIONS.STATUS)
    ) {
      const params = msg.params as { status?: string; isComplete?: boolean };
      if (params?.status === "compacting") {
        this.d.store.updateSession(taskRunId, {
          isCompacting: !params.isComplete,
        });
      }
    }

    if (
      "method" in msg &&
      isNotification(msg.method, POSTHOG_NOTIFICATIONS.COMPACT_BOUNDARY)
    ) {
      this.d.store.updateSession(taskRunId, {
        isCompacting: false,
      });

      this.drainQueuedMessages(taskRunId, session);
    }
  }

  private drainQueuedMessages(
    taskRunId: string,
    session: AgentSession,
  ): boolean {
    const freshSession = this.d.store.getSessions()[taskRunId];
    // A message being edited in place holds back itself and everything after
    // it, so only the sendable prefix counts. When the whole queue is held,
    // this returns false and the caller fires the "turn complete" notification
    // (the agent is idle, waiting for the edit to be saved).
    const hasSendableMessages =
      !!freshSession &&
      freshSession.status === "connected" &&
      sendableQueuePrefixLength(freshSession) > 0;

    if (hasSendableMessages) {
      setTimeout(() => {
        // Re-check at fire time: the turn-end drain and the edit-release flush
        // can each schedule a timer, and whichever fires second must not start
        // a concurrent prompt (the first send flips isPromptPending before it
        // awaits, so this check observes it).
        const latest = this.d.store.getSessionByTaskId(session.taskId);
        if (
          !latest ||
          latest.status !== "connected" ||
          latest.isPromptPending ||
          latest.isCompacting
        ) {
          return;
        }
        this.sendQueuedMessages(session.taskId).catch((err) => {
          this.d.log.error("Failed to send queued messages", {
            taskId: session.taskId,
            error: err,
          });
        });
      }, 0);
    }

    return hasSendableMessages;
  }

  private handlePermissionRequest(
    taskRunId: string,
    payload: Omit<RequestPermissionRequest, "sessionId"> & {
      taskRunId: string;
    },
  ): void {
    this.d.log.info("Permission request received in renderer", {
      taskRunId,
      toolCallId: payload.toolCall.toolCallId,
      title: payload.toolCall.title,
    });

    // A permission request references a tool call from the stream; apply any
    // buffered events first so that tool call is present in the transcript.
    this.flushSessionEventsForTask(taskRunId);

    // Get fresh session state
    const session = this.d.store.getSessions()[taskRunId];
    if (!session) {
      this.d.log.warn("Session not found for permission request", {
        taskRunId,
      });
      return;
    }

    const newPermissions = new Map(session.pendingPermissions);
    // Add receivedAt to create PermissionRequest
    newPermissions.set(payload.toolCall.toolCallId, {
      ...payload,
      receivedAt: Date.now(),
    });

    this.d.store.setPendingPermissions(taskRunId, newPermissions);
    this.d.taskViewedApi.markActivity(session.taskId);
    this.d.notifyPermissionRequest(session.taskTitle, session.taskId);
    this.speakDeterministic(taskRunId, session, "needs_input");
  }

  private handleCloudPermissionRequest(
    taskRunId: string,
    update: DerivedPermissionRequest,
  ): void {
    this.d.log.info("Cloud permission request received", {
      taskRunId,
      requestId: update.requestId,
      toolCallId: update.toolCall.toolCallId,
      title: update.toolCall.title,
    });

    const session = this.d.store.getSessions()[taskRunId];
    if (!session) {
      this.d.log.warn("Session not found for cloud permission request", {
        taskRunId,
      });
      return;
    }

    if (this.respondedCloudPermissionRequestIds.has(update.requestId)) {
      this.d.log.debug("Skipping already-answered cloud permission request", {
        taskRunId,
        requestId: update.requestId,
        toolCallId: update.toolCall.toolCallId,
      });
      return;
    }

    if (
      isPermissionRequestAlreadySurfaced(
        session.pendingPermissions,
        this.cloudPermissionRequestIds.get(update.toolCall.toolCallId),
        update,
      )
    ) {
      return;
    }

    // Store the cloud requestId so we can route the response back
    this.cloudPermissionRequestIds.set(
      update.toolCall.toolCallId,
      update.requestId,
    );

    const newPermissions = new Map(session.pendingPermissions);
    newPermissions.set(update.toolCall.toolCallId, {
      toolCall: update.toolCall as PermissionRequest["toolCall"],
      options: update.options as PermissionRequest["options"],
      taskRunId,
      receivedAt: Date.now(),
    });

    this.d.store.setPendingPermissions(taskRunId, newPermissions);
    this.d.taskViewedApi.markActivity(session.taskId);
    this.d.notifyPermissionRequest(session.taskTitle, session.taskId);
    this.speakDeterministic(taskRunId, session, "needs_input");
  }

  private surfacePersistedPendingPermissions(
    taskRunId: string,
    entries: StoredLogEntry[],
  ): void {
    for (const request of derivePendingPermissionRequests(entries, {
      taskRunId,
    })) {
      this.handleCloudPermissionRequest(taskRunId, request);
    }
  }

  // --- Prompt Handling ---

  /**
   * Send a prompt to the agent.
   * Queues if a prompt is already pending.
   */
  async sendPrompt(
    taskId: string,
    prompt: string | ContentBlock[],
    options?: { steer?: boolean },
  ): Promise<{ stopReason: string }> {
    if (!this.d.getIsOnline()) {
      throw new Error(
        "No internet connection. Please check your connection and try again.",
      );
    }

    let session = this.d.store.getSessionByTaskId(taskId);
    if (!session) throw new Error("No active session for task");

    // The /add-dir dialog mutates the per-task additional-directories list and
    // we re-read it during respawn below. Sending while it's open would race
    // and respawn with the pre-decision set, so block here.
    if (this.d.addDirectoryDialog.open) {
      throw new Error(
        "Confirm the folder access dialog before sending your message.",
      );
    }

    // Steer: the user sent a message mid-turn and asked to fold it into the
    // running turn rather than queue it. Adapters that negotiated
    // `steering: "native"` (Claude, codex) inject at the next tool boundary;
    // unknown local adapters cancel and resend. Cloud sessions only enter this
    // path after the sandbox advertises native steering; compaction still queues.
    if (options?.steer && session.isPromptPending && !session.isCompacting) {
      if (sessionSupportsNativeSteer(session)) {
        if (session.isCloud) {
          if (session.status === "connected") {
            return this.sendCloudPrompt(session, prompt, {
              skipQueueGuard: true,
              steer: true,
            });
          }
        } else {
          return this.sendSteerPrompt(session, prompt);
        }
      }
      if (!session.isCloud) {
        await this.cancelPrompt(taskId);
        const refreshed = this.d.store.getSessionByTaskId(taskId);
        if (refreshed) {
          session = refreshed;
        }
      }
    }

    if (session.isCloud) {
      return this.sendCloudPrompt(session, prompt);
    }

    if (session.status !== "connected") {
      if (session.status === "error") {
        throw new Error(
          session.errorMessage ||
            "Session is in error state. Please retry or start a new session.",
        );
      }
      if (session.status === "connecting") {
        throw new Error(
          "Session is still connecting. Please wait and try again.",
        );
      }
      throw new Error(`Session is not ready (status: ${session.status})`);
    }

    if (session.isPromptPending || session.isCompacting) {
      const promptText = extractPromptText(prompt);
      this.d.store.enqueueMessage(taskId, promptText);
      this.d.log.info("Message queued", {
        taskId,
        queueLength: session.messageQueue.length + 1,
        reason: session.isCompacting ? "compacting" : "prompt_pending",
      });
      return { stopReason: "queued" };
    }

    let blocks = normalizePromptToBlocks(prompt);

    const shellExecutes = getUserShellExecutesSinceLastPrompt(session.events);
    if (shellExecutes.length > 0) {
      const contextBlocks = shellExecutesToContextBlocks(shellExecutes);
      blocks = [...contextBlocks, ...blocks];
    }

    const promptText = extractPromptText(prompt);
    this.d.track(ANALYTICS_EVENTS.PROMPT_SENT, {
      task_id: taskId,
      is_initial: session.events.length === 0,
      execution_type: "local",
      prompt_length_chars: promptText.length,
    });

    // Show the user's message in the chat immediately, before any respawn
    this.applyOptimisticPrompt(session.taskRunId, blocks, promptText);

    if (promptReferencesAbsoluteFolder(prompt)) {
      const repoPath = this.localRepoPaths.get(taskId);
      if (repoPath) {
        try {
          await this.reconnectInPlace(taskId, repoPath);
        } catch (err) {
          this.d.log.error("Respawn failed; aborting prompt send", {
            taskId,
            err,
          });
          this.d.store.clearOptimisticItems(session.taskRunId);
          this.d.store.updateSession(session.taskRunId, {
            isPromptPending: false,
            promptStartedAt: null,
          });
          this.d.toast.error("Couldn't grant the new folder access", {
            description:
              "The session needs to restart to pick up the added folder. Try sending again, or remove the folder reference.",
          });
          throw err instanceof Error
            ? err
            : new Error("Failed to apply additional directories");
        }
        const refreshed = this.d.store.getSessionByTaskId(taskId);
        if (refreshed) {
          session = refreshed;
        }
      }
    }

    return this.sendLocalPrompt(session, blocks, promptText, {
      optimisticApplied: true,
    });
  }

  /**
   * Send a steer message: folded into the turn already running rather than
   * queued. It renders when its `session/prompt` echo arrives and is injected
   * by the agent at the next tool boundary. The running turn keeps ownership of
   * the prompt lifecycle, so this never touches isPromptPending.
   */
  private async sendSteerPrompt(
    session: AgentSession,
    prompt: string | ContentBlock[],
  ): Promise<{ stopReason: string }> {
    const blocks = normalizePromptToBlocks(prompt);
    const promptText = extractPromptText(prompt);

    this.d.track(ANALYTICS_EVENTS.PROMPT_SENT, {
      task_id: session.taskId,
      is_initial: false,
      execution_type: "local",
      prompt_length_chars: promptText.length,
      is_steer: true,
    });

    return this.d.trpc.agent.prompt.mutate({
      sessionId: session.taskRunId,
      prompt: blocks,
      steer: true,
    });
  }

  /**
   * Send the next queued message as its own prompt.
   * Called internally when a turn completes and there are queued messages.
   * Only the head message is dequeued (`max: 1`) so a queue drains one turn at
   * a time — when this turn completes, the drain fires again for the next one.
   * The message is removed from the queue before sending; if sending fails it
   * is lost (acceptable since the user can re-type; avoids complex retry logic).
   */
  private async sendQueuedMessages(
    taskId: string,
  ): Promise<{ stopReason: string }> {
    const combinedText = this.d.store.dequeueMessagesAsText(taskId, {
      stopAtEdited: true,
      max: 1,
    });
    if (!combinedText) {
      return { stopReason: "skipped" };
    }

    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) {
      this.d.log.warn("No session found for queued messages, messages lost", {
        taskId,
        lostMessageLength: combinedText.length,
      });
      return { stopReason: "no_session" };
    }

    this.d.log.info("Sending next queued message as prompt", {
      taskId,
      promptLength: combinedText.length,
    });

    let blocks = normalizePromptToBlocks(combinedText);

    const shellExecutes = getUserShellExecutesSinceLastPrompt(session.events);
    if (shellExecutes.length > 0) {
      const contextBlocks = shellExecutesToContextBlocks(shellExecutes);
      blocks = [...contextBlocks, ...blocks];
    }

    this.d.track(ANALYTICS_EVENTS.PROMPT_SENT, {
      task_id: taskId,
      is_initial: false,
      execution_type: "local",
      prompt_length_chars: combinedText.length,
    });

    try {
      return await this.sendLocalPrompt(session, blocks, combinedText);
    } catch (error) {
      // Log that queued messages were lost due to send failure
      this.d.log.error("Failed to send queued messages, messages lost", {
        taskId,
        lostMessageLength: combinedText.length,
        error,
      });
      throw error;
    }
  }

  private applyOptimisticPrompt(
    taskRunId: string,
    blocks: ContentBlock[],
    promptText: string,
  ): void {
    this.d.store.updateSession(taskRunId, {
      isPromptPending: true,
      promptStartedAt: Date.now(),
      pausedDurationMs: 0,
    });

    const skillButtonId = this.d.h.extractSkillButtonId(blocks);
    if (skillButtonId) {
      this.d.store.appendOptimisticItem(taskRunId, {
        type: "skill_button_action",
        buttonId: skillButtonId,
      });
    } else {
      this.d.store.appendOptimisticItem(taskRunId, {
        type: "user_message",
        content: promptText,
        timestamp: Date.now(),
      });
    }
  }

  private async sendLocalPrompt(
    session: AgentSession,
    blocks: ContentBlock[],
    promptText: string,
    options: { optimisticApplied?: boolean; isRecoveryResend?: boolean } = {},
  ): Promise<{ stopReason: string }> {
    if (!options.optimisticApplied) {
      this.applyOptimisticPrompt(session.taskRunId, blocks, promptText);
    }

    try {
      const result = await this.d.trpc.agent.prompt.mutate({
        sessionId: session.taskRunId,
        prompt: blocks,
      });
      this.d.store.updateSession(session.taskRunId, {
        isPromptPending: false,
        promptStartedAt: null,
      });
      return result;
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      const errorDetails = (error as { data?: { details?: string } }).data
        ?.details;

      this.d.store.clearOptimisticItems(session.taskRunId);

      const limitCause = classifyGatewayLimitError(errorMessage, errorDetails);

      if (limitCause !== null || isRateLimitError(errorMessage, errorDetails)) {
        this.d.log.warn("Gateway limit reached, showing usage limit modal", {
          taskRunId: session.taskRunId,
          cause: limitCause,
        });
        this.d.store.updateSession(session.taskRunId, {
          isPromptPending: false,
          promptStartedAt: null,
        });
        this.d.usageLimit.show(limitCause ? { cause: limitCause } : undefined);
        return { stopReason: "rate_limited" };
      }

      if (isFatalSessionError(errorMessage, errorDetails)) {
        this.d.log.error("Fatal prompt error, attempting recovery", {
          taskRunId: session.taskRunId,
          errorMessage,
          errorDetails,
        });
        if (!options.isRecoveryResend) {
          const resent = await this.recoverAndResendPrompt(
            session,
            blocks,
            promptText,
            errorDetails || errorMessage,
          );
          if (resent) {
            return resent;
          }
        }
        // Recovery failed (or this already was the post-recovery resend):
        // surface the error state so the user can retry manually.
        const latest = this.d.store.getSessionByTaskId(session.taskId);
        if (
          latest?.taskRunId === session.taskRunId &&
          latest.status !== "error"
        ) {
          this.setErrorSession(
            session.taskId,
            session.taskRunId,
            session.taskTitle,
            errorDetails ||
              "Session connection lost. Please retry or start a new session.",
            "Connection lost",
          );
        }
      } else {
        this.d.store.updateSession(session.taskRunId, {
          isPromptPending: false,
          isCompacting: false,
          promptStartedAt: null,
        });
      }

      // A provider request that timed out or dropped leaves the session
      // healthy — no recovery ran above — so tell the user to just re-send
      // instead of surfacing the raw "Internal error: API Error: …" text.
      if (isTransientUpstreamError(errorMessage, errorDetails)) {
        this.d.log.warn("Transient upstream provider failure during prompt", {
          taskRunId: session.taskRunId,
          errorMessage,
          errorDetails,
        });
        throw new Error(
          "The AI provider timed out or dropped the connection. Your session is unaffected — please send the message again.",
          { cause: error },
        );
      }

      throw error;
    }
  }

  /**
   * A fatal prompt failure (e.g. "Session not found") usually means the
   * backend agent was idle-killed or the host process restarted while the
   * renderer still shows the session as connected. Recover the session in
   * place and resend the prompt once, so a reply to a stale session lands
   * instead of erroring and losing the user's message.
   *
   * Returns the resend result, or null when recovery (or the refreshed
   * session lookup) failed and the caller should surface the original error.
   */
  private async recoverAndResendPrompt(
    session: AgentSession,
    blocks: ContentBlock[],
    promptText: string,
    reason: string,
  ): Promise<{ stopReason: string } | null> {
    let recovered = false;
    try {
      recovered = await this.tryAutoRecoverLocalSession(
        session.taskId,
        session.taskRunId,
        reason,
      );
    } catch (recoveryError) {
      this.d.log.warn("Session recovery threw while resending prompt", {
        taskId: session.taskId,
        taskRunId: session.taskRunId,
        error:
          recoveryError instanceof Error
            ? recoveryError.message
            : String(recoveryError),
      });
      return null;
    }
    if (!recovered) return null;

    const refreshed = this.d.store.getSessionByTaskId(session.taskId);
    if (
      !refreshed ||
      refreshed.taskRunId !== session.taskRunId ||
      refreshed.status !== "connected"
    ) {
      return null;
    }

    this.d.log.info("Resending prompt after session recovery", {
      taskId: session.taskId,
      taskRunId: session.taskRunId,
    });
    return this.sendLocalPrompt(refreshed, blocks, promptText, {
      isRecoveryResend: true,
    });
  }

  /**
   * Steer a single queued message into the running turn now: drop it from the
   * queue and resend it as a steer. Native (Claude, local) injects at the next
   * tool boundary; cloud/Codex interrupt and resend. The rest of the queue is
   * left in place and drains when the turn ends. Rolls the message back onto
   * the queue if the send fails so it is not silently lost.
   */
  async steerQueuedMessage(taskId: string, messageId: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;
    // Steer falls through to the queue during compaction, which would re-enqueue
    // the message as plain text and drop its rawPrompt. Leave it queued; it
    // drains normally once compaction ends.
    if (session.isCompacting) return;
    const message = session.messageQueue.find((m) => m.id === messageId);
    if (!message) return;

    this.d.store.removeQueuedMessage(taskId, messageId);
    try {
      await this.sendPrompt(taskId, message.rawPrompt ?? message.content, {
        steer: true,
      });
    } catch (error) {
      this.d.store.prependQueuedMessages(taskId, [message]);
      throw error;
    }
  }

  /**
   * Begin an in-place edit of a queued message: mark it as the edit target so
   * that, until the edit is saved or cancelled, it and everything queued after
   * it are held back when the turn ends (only the messages before it may send).
   */
  setEditingQueuedMessage(taskId: string, messageId: string): void {
    this.d.store.setEditingQueuedMessage(taskId, messageId);
  }

  /**
   * Release an in-place edit hold — the edit was cancelled, or the edited
   * message left the queue. Drops the hold and, if the agent is now idle, sends
   * the messages the hold was blocking (the turn may have ended while the user
   * was still editing, so nothing else would trigger the drain).
   */
  clearEditingQueuedMessage(taskId: string): void {
    this.d.store.clearEditingQueuedMessage(taskId);
    this.flushQueuedMessagesIfIdle(taskId);
  }

  /**
   * Update a queued message in place from an edited composer prompt, keeping it
   * in the queue at its current position. Mirrors the enqueue normalization so
   * the stored `content`/`rawPrompt` match what a freshly-queued prompt would
   * hold (cloud recomputes the transport display + raw payload; local stores
   * the serialized text). Returns false when the target is no longer queued so
   * the caller can fall back to sending it as a new message.
   *
   * Saving is also what releases the edit hold: the hold is cleared and, if the
   * agent finished its turn while the user was editing, the now-unblocked queue
   * is drained.
   */
  async updateQueuedMessage(
    taskId: string,
    messageId: string,
    prompt: string | ContentBlock[],
  ): Promise<boolean> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return false;
    if (!session.messageQueue.some((m) => m.id === messageId)) return false;

    if (session.isCloud) {
      const normalizedPrompt = await this.resolveCloudPrompt(prompt);
      // Cloud normalization awaits, during which the message may have drained
      // (a turn completed and sent it). Re-check against fresh state: without
      // this, the store update below is a silent no-op yet we'd still report a
      // successful save, so the caller wouldn't fall back to sending the edit
      // as a fresh message and the edit would be lost.
      const fresh = this.d.store.getSessionByTaskId(taskId);
      if (!fresh?.messageQueue.some((m) => m.id === messageId)) return false;
      const transport = this.d.h.getCloudPromptTransport(normalizedPrompt);
      this.d.store.updateQueuedMessage(taskId, messageId, {
        content: transport.promptText,
        rawPrompt: normalizedPrompt,
      });
    } else {
      this.d.store.updateQueuedMessage(taskId, messageId, {
        content: extractPromptText(prompt),
      });
    }

    // Read fresh: the cloud path awaited above, so the pre-await `session`
    // snapshot may be stale for the edit-hold decision.
    const latest = this.d.store.getSessionByTaskId(taskId);
    if (latest?.editingQueuedId === messageId) {
      this.d.store.clearEditingQueuedMessage(taskId);
    }
    this.flushQueuedMessagesIfIdle(taskId);
    return true;
  }

  /**
   * Nudge the queue after an in-place edit is saved or cancelled. The turn may
   * have finished while the user was editing — in that case nothing else would
   * trigger the normal turn-end drain, so the now-unblocked messages would sit
   * stranded until the next turn. Only sends when the agent is actually idle;
   * a mid-turn edit is left for the turn-end drain to pick up.
   */
  private flushQueuedMessagesIfIdle(taskId: string): void {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session || session.messageQueue.length === 0) return;

    if (session.isCloud) {
      // The cloud flush re-checks run readiness itself, so scheduling while the
      // run is still busy is a safe no-op.
      this.scheduleCloudQueueFlush(taskId, "edit_released");
      return;
    }

    if (
      session.status === "connected" &&
      !session.isPromptPending &&
      !session.isCompacting
    ) {
      this.drainQueuedMessages(session.taskRunId, session);
    }
  }

  /**
   * Cancel the current prompt.
   */
  async cancelPrompt(taskId: string): Promise<boolean> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return false;

    this.d.store.updateSession(session.taskRunId, {
      isPromptPending: false,
      promptStartedAt: null,
    });

    if (session.isCloud) {
      return this.cancelCloudPrompt(session);
    }

    try {
      const result = await this.d.trpc.agent.cancelPrompt.mutate({
        sessionId: session.taskRunId,
      });

      const durationSeconds = Math.round(
        (Date.now() - session.startedAt) / 1000,
      );
      const promptCount = session.events.filter(
        (e) => "method" in e.message && e.message.method === "session/prompt",
      ).length;
      this.d.track(ANALYTICS_EVENTS.TASK_RUN_CANCELLED, {
        task_id: taskId,
        execution_type: "local",
        duration_seconds: durationSeconds,
        prompts_sent: promptCount,
      });

      return result;
    } catch (error) {
      this.d.log.error("Failed to cancel prompt", error);
      return false;
    }
  }

  // --- Cloud Commands ---

  private async sendCloudPrompt(
    session: AgentSession,
    prompt: string | ContentBlock[],
    options?: { skipQueueGuard?: boolean; steer?: boolean },
  ): Promise<{ stopReason: string }> {
    const normalizedPrompt = await this.resolveCloudPrompt(prompt);
    const transport = this.d.h.getCloudPromptTransport(normalizedPrompt);
    if (
      !transport.messageText &&
      transport.filePaths.length === 0 &&
      transport.skillBundles.length === 0
    ) {
      return { stopReason: "empty" };
    }

    if (isTerminalStatus(session.cloudStatus)) {
      // If the agent never booted (no `run_started`), resuming spins another
      // sandbox that hits the same provisioning failure — surface the error
      // instead of looping.
      if (session.cloudStatus === "failed" && session.status !== "connected") {
        throw new Error(
          session.cloudErrorMessage ??
            "Cloud run couldn't start. Check that GitHub is connected for this project, then try again.",
        );
      }
      return this.resumeCloudRun(session, normalizedPrompt);
    }

    if (session.cloudStatus !== "in_progress") {
      this.d.store.enqueueMessage(
        session.taskId,
        transport.promptText,
        normalizedPrompt,
      );
      this.d.log.info("Cloud message queued (sandbox not ready)", {
        taskId: session.taskId,
        cloudStatus: session.cloudStatus,
      });
      return { stopReason: "queued" };
    }

    // Agent-readiness guard: until we've received `_posthog/run_started`
    // (which flips `session.status` to `"connected"`), the agent may
    // still be booting / restoring after a sandbox restart, or mid-
    // initial-prompt — sending now would race with its
    // `clientConnection.prompt(initialPrompt)` on the same ACP session.
    // Funnel through the queue; the run_started or turn_complete
    // handlers will drain it once the agent is provably ready.
    if (
      !options?.skipQueueGuard &&
      session.isCloud &&
      session.status !== "connected"
    ) {
      this.d.store.enqueueMessage(
        session.taskId,
        transport.promptText,
        normalizedPrompt,
      );
      this.d.log.info("Cloud message queued (agent not ready)", {
        taskId: session.taskId,
        sessionStatus: session.status,
        queueLength: session.messageQueue.length + 1,
      });
      // The watcher may have exhausted its reconnect budget and been left in a
      // failed state — without an SSE stream, no `turn_complete` will arrive
      // to drain the queue. Kick a retry so the stream comes back online; the
      // queued message dispatches naturally once `run_started`/`turn_complete`
      // is observed.
      if (session.status === "disconnected" || session.status === "error") {
        this.retryCloudTaskWatch(session.taskId).catch((err) => {
          this.d.log.warn(
            "Auto-retry of cloud task watch from queue gate failed",
            {
              taskId: session.taskId,
              error: String(err),
            },
          );
        });
      }
      return { stopReason: "queued" };
    }

    if (!options?.skipQueueGuard && session.isPromptPending) {
      this.d.store.enqueueMessage(
        session.taskId,
        transport.promptText,
        normalizedPrompt,
      );
      this.d.log.info("Cloud message queued", {
        taskId: session.taskId,
        queueLength: session.messageQueue.length + 1,
      });
      return { stopReason: "queued" };
    }

    const authStatus = await this.getAuthCredentialsStatus();
    if (authStatus.kind === "restoring") {
      return this.queueRestoringCloudPrompt(
        session,
        normalizedPrompt,
        "Cloud message queued (auth restoring)",
      );
    }

    const cloudCommandAuth = await this.getCloudCommandAuth();
    if (authStatus.kind !== "ready" || !cloudCommandAuth) {
      throw new Error("Authentication required for cloud commands");
    }
    const { auth } = authStatus;

    this.watchCloudTask(
      session.taskId,
      session.taskRunId,
      cloudCommandAuth.apiHost,
      cloudCommandAuth.teamId,
      undefined,
      session.logUrl,
      undefined,
      session.adapter ?? "claude",
    );

    const artifactIds = await this.d.h.uploadRunAttachments(
      auth.client,
      session.taskId,
      session.taskRunId,
      transport.filePaths,
      transport.skillBundles,
    );
    const params: Record<string, unknown> = {};
    if (transport.messageText) {
      params.content = transport.messageText;
    }
    if (artifactIds.length > 0) {
      params.artifact_ids = artifactIds;
    }
    if (options?.steer) {
      params.steer = true;
    }

    const currentSessionBeforeSend =
      this.getSessionByRunId(session.taskRunId) ?? session;
    const idleEvidenceBeforeSend = this.cloudRunIdleTracker.capture(
      currentSessionBeforeSend,
    );
    if (!options?.steer) {
      this.d.store.updateSession(session.taskRunId, {
        isPromptPending: true,
        promptStartedAt: Date.now(),
        pausedDurationMs: 0,
        agentIdleForRunId: undefined,
      });
      this.cloudRunIdleTracker.markBusy(currentSessionBeforeSend);
    }
    this.d.store.appendOptimisticItem(session.taskRunId, {
      type: "user_message",
      content: transport.promptText,
      timestamp: Date.now(),
      pinToTop: false,
    });

    this.d.track(ANALYTICS_EVENTS.PROMPT_SENT, {
      task_id: session.taskId,
      is_initial: session.events.length === 0,
      execution_type: "cloud",
      prompt_length_chars: transport.promptText.length,
      ...(options?.steer ? { is_steer: true } : {}),
    });

    try {
      const result = await this.d.trpc.cloudTask.sendCommand.mutate({
        taskId: session.taskId,
        runId: session.taskRunId,
        apiHost: cloudCommandAuth.apiHost,
        teamId: cloudCommandAuth.teamId,
        method: "user_message",
        params,
      });

      if (!result.success) {
        throw new Error(result.error ?? "Failed to send cloud command");
      }

      const commandResult = result.result as
        | { queued?: boolean; steered?: boolean; stopReason?: string }
        | undefined;
      const stopReason = commandResult?.queued
        ? "queued"
        : (commandResult?.stopReason ?? "end_turn");

      return { stopReason };
    } catch (error) {
      if (!options?.steer) {
        this.d.store.updateSession(session.taskRunId, {
          isPromptPending: false,
          promptStartedAt: null,
        });
      }
      this.d.store.clearTailOptimisticItems(session.taskRunId);
      const currentSessionAfterFailure = this.getSessionByRunId(
        session.taskRunId,
      );
      if (currentSessionAfterFailure && !options?.steer) {
        const restoreResult = this.cloudRunIdleTracker.restoreAfterFailedSend(
          idleEvidenceBeforeSend,
          currentSessionAfterFailure,
        );
        if (restoreResult) {
          this.d.log.warn("Restored idle evidence after failed cloud send", {
            taskId: session.taskId,
            taskRunId: session.taskRunId,
          });
          if (
            currentSessionAfterFailure.agentIdleForRunId !==
            restoreResult.agentIdleForRunId
          ) {
            this.d.store.updateSession(session.taskRunId, {
              agentIdleForRunId: restoreResult.agentIdleForRunId,
            });
          }
        }
      }
      throw error;
    }
  }

  /**
   * Dispatches all currently queued cloud messages as a single combined
   * prompt. Drains the queue up-front and rolls it back on failure so the
   * next dispatch trigger (turn_complete, cloudStatus flip) can retry. A
   * per-taskId re-entrance guard prevents concurrent triggers from
   * double-dispatching.
   *
   * Pre-flight conditions match what `sendCloudPrompt` would otherwise
   * silently re-queue on (sandbox not in_progress, prompt already pending).
   * Skipping early lets the next trigger retry instead of re-queueing the
   * already-dequeued prompt back into the same queue.
   */
  private async sendQueuedCloudMessages(
    taskId: string,
    options?: { force?: boolean },
  ): Promise<void> {
    if (this.dispatchingCloudQueues.has(taskId)) return;

    this.dispatchingCloudQueues.add(taskId);
    try {
      const session = this.d.store.getSessionByTaskId(taskId);
      if (!session?.isCloud || session.messageQueue.length === 0) return;
      // Terminal cloud runs route through `resumeCloudRun`, which spins a
      // new run and consumes the prompt itself — so dispatch is fine.
      // Otherwise gate on the agent-ready handshake (`run_started` flips
      // status to "connected") to avoid racing with `sendInitialTaskMessage`.
      const isTerminal = isTerminalStatus(session.cloudStatus);
      const canSendNow =
        isTerminal ||
        (session.cloudStatus === "in_progress" &&
          (session.status === "connected" || options?.force === true));
      if (!canSendNow || session.isPromptPending) return;

      // Draining while auth is still restoring would route through the restoring
      // gate in sendCloudPrompt, re-enqueueing a single merged prompt and losing
      // the original message boundaries. The auth-restored flush re-runs this
      // once credentials are ready.
      const authStatus = await this.getAuthCredentialsStatus();
      if (authStatus.kind === "restoring") return;

      // Drain one message per turn (`max: 1`) so a queue sends sequentially:
      // the next turn_complete flushes the next message. A later flush after
      // this send finishes picks up the rest.
      const drained = this.d.store.dequeueMessages(taskId, {
        stopAtEdited: true,
        max: 1,
      });
      const combined = this.d.h.combineQueuedCloudPrompts(drained);
      if (!combined) return;

      this.d.log.info("Sending next queued cloud message", {
        taskId,
        drainedCount: drained.length,
      });

      try {
        await this.sendCloudPrompt(session, combined, {
          skipQueueGuard: true,
        });
      } catch (err) {
        this.d.log.warn("Cloud queue dispatch failed; re-enqueueing", {
          taskId,
          error: String(err),
        });
        this.d.store.prependQueuedMessages(taskId, drained);
      }
    } finally {
      this.dispatchingCloudQueues.delete(taskId);
    }
  }

  private async resumeCloudRun(
    session: AgentSession,
    prompt: string | ContentBlock[],
  ): Promise<{ stopReason: string }> {
    const normalizedPrompt = await this.resolveCloudPrompt(prompt);
    const authStatus = await this.getAuthCredentialsStatus();
    if (authStatus.kind === "restoring") {
      return this.queueRestoringCloudPrompt(
        session,
        normalizedPrompt,
        "Cloud resume queued (auth restoring)",
      );
    }
    if (authStatus.kind !== "ready") {
      throw new Error("Authentication required for cloud commands");
    }
    const authCredentials = authStatus.auth;

    const auth = await this.getCloudCommandAuth();
    if (!auth) {
      throw new Error("Authentication required for cloud commands");
    }

    const transport = this.d.h.getCloudPromptTransport(normalizedPrompt);
    if (
      !transport.messageText &&
      transport.filePaths.length === 0 &&
      transport.skillBundles.length === 0
    ) {
      return { stopReason: "empty" };
    }
    this.d.store.updateSession(session.taskRunId, {
      isPromptPending: true,
      promptStartedAt: Date.now(),
      pausedDurationMs: 0,
    });
    this.d.store.appendOptimisticItem(session.taskRunId, {
      type: "user_message",
      content: transport.promptText,
      timestamp: Date.now(),
      pinToTop: false,
    });

    const rollbackOptimisticPrompt = () => {
      this.d.store.updateSession(session.taskRunId, {
        isPromptPending: false,
        promptStartedAt: null,
      });
      this.d.store.clearTailOptimisticItems(session.taskRunId);
    };

    let updatedTask: Task;
    let runtimeOptions: CloudRuntimeOptions;
    try {
      const artifactIds = await this.d.h.uploadTaskStagedAttachments(
        authCredentials.client,
        session.taskId,
        transport.filePaths,
        transport.skillBundles,
      );

      const previousRun = await authCredentials.client.getTaskRun(
        session.taskId,
        session.taskRunId,
      );
      const previousState = previousRun.state as Record<string, unknown>;
      const previousOutput = (previousRun.output ?? {}) as Record<
        string,
        unknown
      >;
      // Prefer the branch the agent last pushed to, then the run branch, then
      // the base branch — preserves unmerged work if the sandbox is rebuilt.
      const previousBaseBranch =
        (typeof previousOutput.head_branch === "string"
          ? previousOutput.head_branch
          : null) ??
        previousRun.branch ??
        (typeof previousState.pr_base_branch === "string"
          ? previousState.pr_base_branch
          : null) ??
        session.cloudBranch;
      const prAuthorshipMode = getCloudPrAuthorshipMode(previousState);

      this.d.log.info("Creating resume run for terminal cloud task", {
        taskId: session.taskId,
        previousRunId: session.taskRunId,
        previousStatus: session.cloudStatus,
      });

      runtimeOptions = getCloudRuntimeOptions(session, previousRun);

      // Backend derives the snapshot from resumeFromRunId and restores the sandbox.
      updatedTask = await authCredentials.client.runTaskInCloud(
        session.taskId,
        previousBaseBranch,
        {
          adapter: runtimeOptions.adapter,
          model: runtimeOptions.model,
          reasoningLevel: runtimeOptions.reasoningLevel,
          initialPermissionMode: runtimeOptions.initialPermissionMode,
          resumeFromRunId: session.taskRunId,
          pendingUserMessage: transport.messageText,
          pendingUserArtifactIds:
            artifactIds.length > 0 ? artifactIds : undefined,
          prAuthorshipMode,
          autoPublish: previousState.auto_publish === true || undefined,
          rtkEnabled: this.d.settings.rtkEnabledCloud,
          runSource: getCloudRunSource(previousState),
          signalReportId:
            typeof previousState.signal_report_id === "string"
              ? previousState.signal_report_id
              : undefined,
        },
      );
    } catch (error) {
      rollbackOptimisticPrompt();
      throw error;
    }
    const newRun = updatedTask.latest_run;
    if (!newRun?.id) {
      rollbackOptimisticPrompt();
      throw new Error("Failed to create resume run");
    }

    this.supersededRunIds.add(session.taskRunId);
    while (this.supersededRunIds.size > MAX_SUPERSEDED_RUN_IDS) {
      const oldest = this.supersededRunIds.values().next().value;
      if (oldest === undefined) break;
      this.supersededRunIds.delete(oldest);
    }

    // New-run session carrying the prior conversation; setSession drops the old one.
    const newSession = createBaseSession(
      newRun.id,
      session.taskId,
      session.taskTitle,
    );
    newSession.status = "disconnected";
    newSession.isCloud = true;
    newSession.isPromptPending = true;
    newSession.promptStartedAt = Date.now();
    newSession.events = [...session.events];
    newSession.optimisticItems = (
      this.getSessionByRunId(session.taskRunId)?.optimisticItems ?? []
    ).filter((item) => item.type === "user_message" && item.pinToTop === false);
    const resumeFromEntryCount =
      session.cloudTranscriptEntryCount ?? session.processedLineCount ?? 0;
    newSession.cloudTranscriptEntryCount = resumeFromEntryCount;
    newSession.processedLineCount = 0;
    this.d.store.setSession(newSession);

    // Start the watcher immediately so we don't miss status updates.
    const initialMode =
      typeof newRun.state?.initial_permission_mode === "string"
        ? newRun.state.initial_permission_mode
        : undefined;
    const priorModel = getConfigOptionByCategory(
      session.configOptions,
      "model",
    )?.currentValue;
    const initialModel =
      newRun.model ?? (typeof priorModel === "string" ? priorModel : undefined);
    const initialReasoningEffort =
      newRun.reasoning_effort ?? runtimeOptions.reasoningLevel;
    this.watchCloudTask(
      session.taskId,
      newRun.id,
      auth.apiHost,
      auth.teamId,
      undefined,
      newRun.log_url,
      initialMode,
      newRun.runtime_adapter ?? session.adapter ?? "claude",
      initialModel,
      undefined,
      resumeFromEntryCount,
      undefined,
      initialReasoningEffort,
      newRun.state,
    );

    this.d.queryClient.invalidateQueries({ queryKey: ["tasks"] });

    this.d.track(ANALYTICS_EVENTS.PROMPT_SENT, {
      task_id: session.taskId,
      is_initial: false,
      execution_type: "cloud",
      prompt_length_chars: transport.promptText.length,
    });

    return { stopReason: "queued" };
  }

  private async cancelCloudPrompt(session: AgentSession): Promise<boolean> {
    if (isTerminalStatus(session.cloudStatus)) {
      this.d.log.info("Skipping cancel for terminal cloud run", {
        taskId: session.taskId,
        status: session.cloudStatus,
      });
      return false;
    }

    const auth = await this.getCloudCommandAuth();
    if (!auth) {
      this.d.log.error("No auth for cloud cancel");
      return false;
    }

    try {
      const result = await this.d.trpc.cloudTask.sendCommand.mutate({
        taskId: session.taskId,
        runId: session.taskRunId,
        apiHost: auth.apiHost,
        teamId: auth.teamId,
        method: "cancel",
      });

      const durationSeconds = Math.round(
        (Date.now() - session.startedAt) / 1000,
      );
      const promptCount = session.events.filter(
        (e) => "method" in e.message && e.message.method === "session/prompt",
      ).length;
      this.d.track(ANALYTICS_EVENTS.TASK_RUN_CANCELLED, {
        task_id: session.taskId,
        execution_type: "cloud",
        duration_seconds: durationSeconds,
        prompts_sent: promptCount,
      });

      if (!result.success) {
        this.d.log.warn("Cloud cancel command failed", { error: result.error });
        return false;
      }

      return true;
    } catch (error) {
      this.d.log.error("Failed to cancel cloud prompt", error);
      return false;
    }
  }

  async stopCloudRun(taskId: string, runId?: string): Promise<boolean> {
    const session = this.d.store.getSessionByTaskId(taskId);
    let taskRunId: string;
    try {
      const client = await this.d.getAuthenticatedClient();
      if (!client) return false;
      const task = (await client.getTask(taskId)) as Task;
      const latestRun = task.latest_run;
      if (!latestRun || latestRun.environment !== "cloud") {
        return true;
      }
      if (isTerminalStatus(latestRun.status)) {
        const rendererStillExpectsCompletion =
          session?.isCloud === true &&
          session.taskRunId === latestRun.id &&
          !isTerminalStatus(session.cloudStatus);
        if (!rendererStillExpectsCompletion) {
          return true;
        }
      }
      taskRunId = latestRun.id;
      if (runId && runId !== taskRunId) {
        this.d.log.warn("Refusing to stop a newer cloud run", {
          taskId,
          requestedRunId: runId,
          taskRunId,
        });
        return false;
      }
    } catch (error) {
      this.d.log.error("Failed to resolve current cloud run", error);
      return false;
    }

    const matchingSession =
      session?.isCloud && session.taskRunId === taskRunId ? session : undefined;
    const previousPromptState = matchingSession
      ? {
          isPromptPending: matchingSession.isPromptPending,
          promptStartedAt: matchingSession.promptStartedAt,
        }
      : undefined;
    if (matchingSession) {
      this.d.store.updateSession(matchingSession.taskRunId, {
        stopRequested: true,
        isPromptPending: false,
        promptStartedAt: null,
      });
    }

    try {
      const result = await this.d.trpc.cloudTask.stop.mutate({
        taskId,
        runId: taskRunId,
      });

      if (!result.success) {
        if (matchingSession) {
          this.d.store.updateSession(matchingSession.taskRunId, {
            stopRequested: false,
            ...previousPromptState,
          });
        }
        this.d.log.warn("Cloud run stop failed", {
          taskId,
          error: result.error,
          retryable: result.retryable,
        });
        return false;
      }

      const durationSeconds = matchingSession
        ? Math.round((Date.now() - matchingSession.startedAt) / 1000)
        : undefined;
      const promptCount = matchingSession?.events.filter(
        (e) => "method" in e.message && e.message.method === "session/prompt",
      ).length;
      this.d.track(ANALYTICS_EVENTS.TASK_RUN_STOPPED, {
        task_id: taskId,
        execution_type: "cloud",
        ...(durationSeconds === undefined
          ? {}
          : { duration_seconds: durationSeconds }),
        ...(promptCount === undefined ? {} : { prompts_sent: promptCount }),
      });

      return true;
    } catch (error) {
      if (matchingSession) {
        this.d.store.updateSession(matchingSession.taskRunId, {
          stopRequested: false,
          ...previousPromptState,
        });
      }
      this.d.log.error("Failed to stop cloud run", error);
      return false;
    }
  }

  private async getCloudCommandAuth(): Promise<{
    apiHost: string;
    teamId: number;
  } | null> {
    const authState = await this.d.fetchAuthState();
    if (!authState.cloudRegion || !authState.currentProjectId) return null;
    return {
      apiHost: getCloudUrlFromRegion(authState.cloudRegion),
      teamId: authState.currentProjectId,
    };
  }

  /**
   * Send a command to the cloud agent server via the backend proxy.
   * Handles auth lookup and throws if credentials are unavailable.
   */
  private async sendCloudCommand(
    session: AgentSession,
    method: "permission_response" | "set_config_option",
    params: Record<string, unknown>,
  ): Promise<void> {
    const auth = await this.getCloudCommandAuth();
    if (!auth) {
      throw new Error("No cloud auth credentials available");
    }
    await this.d.trpc.cloudTask.sendCommand.mutate({
      taskId: session.taskId,
      runId: session.taskRunId,
      apiHost: auth.apiHost,
      teamId: auth.teamId,
      method,
      params,
    });
  }

  private async refreshCloudRunStatus(
    session: AgentSession,
  ): Promise<TaskRunStatus | null> {
    const authStatus = await this.getAuthCredentialsStatus();
    if (authStatus.kind !== "ready") {
      return null;
    }

    try {
      const run = await authStatus.auth.client.getTaskRun(
        session.taskId,
        session.taskRunId,
      );
      this.d.store.updateSession(session.taskRunId, {
        cloudStatus: run.status,
        cloudStage: run.stage ?? null,
        cloudOutput: run.output ?? null,
        cloudArtifacts: run.artifacts ?? [],
        cloudErrorMessage: run.error_message,
        logUrl: run.log_url ?? session.logUrl,
      });
      return run.status;
    } catch (error) {
      this.d.log.warn("Failed to refresh cloud run status", {
        taskId: session.taskId,
        taskRunId: session.taskRunId,
        error: String(error),
      });
      return null;
    }
  }

  private async resumeTerminalCloudPermissionResponse(
    session: AgentSession,
    permission: PermissionRequest | undefined,
    toolCallId: string,
    requestId: string | undefined,
    optionId: string,
    customInput?: string,
    answers?: Record<string, string>,
    cloudStatus?: TaskRunStatus | null,
  ): Promise<void> {
    this.cloudPermissionRequestIds.delete(toolCallId);
    const answerPrompt = formatPermissionAnswerPrompt(
      permission,
      optionId,
      customInput,
      answers,
    );
    if (answerPrompt) {
      await this.sendCloudPrompt(
        { ...session, cloudStatus: cloudStatus ?? session.cloudStatus },
        answerPrompt,
      );
      this.d.log.info("Permission answer resumed terminal cloud run", {
        taskId: session.taskId,
        toolCallId,
        optionId,
      });
    } else {
      this.d.log.info("Dropped permission response for terminal cloud run", {
        taskId: session.taskId,
        toolCallId,
        optionId,
      });
    }
    await this.persistCloudPermissionResolution(
      session.taskId,
      permission?.taskRunId ?? session.taskRunId,
      toolCallId,
      requestId,
      optionId,
    );
  }

  /**
   * Record a response to a permission request whose sandbox is gone. A live
   * sandbox writes `_posthog/permission_resolved` to the run log when it
   * resolves a request, but a request answered after its run terminalized has
   * no sandbox left to do that — without this record the request stays
   * pending in the persisted log forever, and every future derivation (app
   * restart, another device, a session rebuild) re-surfaces the
   * already-answered question as a fresh card.
   */
  private async persistCloudPermissionResolution(
    taskId: string,
    taskRunId: string,
    toolCallId: string,
    requestId: string | undefined,
    optionId: string,
  ): Promise<void> {
    if (!requestId) return;
    this.markCloudPermissionResponded(requestId);

    const client = await this.d.getAuthenticatedClient();
    if (!client) return;
    try {
      await client.appendTaskRunLog(taskId, taskRunId, [
        {
          type: "notification",
          timestamp: new Date().toISOString(),
          notification: {
            method: POSTHOG_NOTIFICATIONS.PERMISSION_RESOLVED,
            params: { requestId, toolCallId, optionId },
          },
        },
      ]);
    } catch (error) {
      this.d.log.warn("Failed to persist permission resolution to run log", {
        taskId,
        taskRunId,
        toolCallId,
        error,
      });
    }
  }

  private markCloudPermissionResponded(requestId: string): void {
    this.respondedCloudPermissionRequestIds.add(requestId);
    // add() grows the set by at most one, so one eviction restores the cap.
    if (
      this.respondedCloudPermissionRequestIds.size >
      MAX_RESPONDED_PERMISSION_REQUEST_IDS
    ) {
      const oldest = this.respondedCloudPermissionRequestIds
        .values()
        .next().value;
      if (oldest !== undefined) {
        this.respondedCloudPermissionRequestIds.delete(oldest);
      }
    }
  }

  // --- Permissions ---

  private resolvePermission(session: AgentSession, toolCallId: string): void {
    const permission = session.pendingPermissions.get(toolCallId);
    const newPermissions = new Map(session.pendingPermissions);
    newPermissions.delete(toolCallId);
    this.d.store.setPendingPermissions(session.taskRunId, newPermissions);

    if (permission?.receivedAt) {
      this.d.store.updateSession(session.taskRunId, {
        pausedDurationMs:
          (session.pausedDurationMs ?? 0) +
          (Date.now() - permission.receivedAt),
      });
    }
  }

  /**
   * Respond to a permission request.
   */
  async respondToPermission(
    taskId: string,
    toolCallId: string,
    optionId: string,
    customInput?: string,
    answers?: Record<string, string>,
  ): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) {
      this.d.log.error("No session found for permission response", { taskId });
      return;
    }

    const permission = session.pendingPermissions.get(toolCallId);
    this.d.track(ANALYTICS_EVENTS.PERMISSION_RESPONDED, {
      task_id: taskId,
      ...this.d.buildPermissionToolMetadata(permission, optionId, customInput),
    });

    const cloudRequestId = this.cloudPermissionRequestIds.get(toolCallId);
    this.resolvePermission(session, toolCallId);

    try {
      const refreshedCloudStatus =
        session.isCloud && !isTerminalStatus(session.cloudStatus)
          ? await this.refreshCloudRunStatus(session)
          : null;
      const terminalCloudStatus = isTerminalStatus(session.cloudStatus)
        ? session.cloudStatus
        : refreshedCloudStatus;

      if (session.isCloud && isTerminalStatus(terminalCloudStatus)) {
        // The run is over: complete_task drained the sandbox's pending
        // permission promise, and permission_response only proxies to an active
        // sandbox. Carry the selected answer forward as a user message instead.
        await this.resumeTerminalCloudPermissionResponse(
          session,
          permission,
          toolCallId,
          cloudRequestId,
          optionId,
          customInput,
          answers,
          terminalCloudStatus,
        );
        return;
      }
      if (session.isCloud && cloudRequestId) {
        this.cloudPermissionRequestIds.delete(toolCallId);
        try {
          await this.sendCloudCommand(session, "permission_response", {
            requestId: cloudRequestId,
            optionId,
            customInput,
            answers,
          });
        } catch (error) {
          const latestCloudStatus = await this.refreshCloudRunStatus(session);
          if (isTerminalStatus(latestCloudStatus)) {
            await this.resumeTerminalCloudPermissionResponse(
              session,
              permission,
              toolCallId,
              cloudRequestId,
              optionId,
              customInput,
              answers,
              latestCloudStatus,
            );
            return;
          }
          throw error;
        }
        // The live sandbox persists its own resolved marker; remember the
        // response locally so a snapshot fetched before that marker flushes
        // to storage cannot re-surface the question.
        this.markCloudPermissionResponded(cloudRequestId);
      } else {
        await this.d.trpc.agent.respondToPermission.mutate({
          taskRunId: session.taskRunId,
          toolCallId,
          optionId,
          customInput,
          answers,
        });
      }

      this.d.log.info("Permission response sent", {
        taskId,
        toolCallId,
        optionId,
        isCloud: !!cloudRequestId,
        hasCustomInput: !!customInput,
      });
    } catch (error) {
      this.d.log.error("Failed to respond to permission", {
        taskId,
        toolCallId,
        optionId,
        error,
      });
    }
  }

  /**
   * Cancel a permission request.
   */
  async cancelPermission(taskId: string, toolCallId: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) {
      this.d.log.error("No session found for permission cancellation", {
        taskId,
      });
      return;
    }

    const permission = session.pendingPermissions.get(toolCallId);
    this.d.track(ANALYTICS_EVENTS.PERMISSION_CANCELLED, {
      task_id: taskId,
      ...this.d.buildPermissionToolMetadata(permission),
    });

    const cloudRequestId = this.cloudPermissionRequestIds.get(toolCallId);
    this.resolvePermission(session, toolCallId);

    try {
      if (session.isCloud && isTerminalStatus(session.cloudStatus)) {
        // The run is over — the card was resolved locally above and there is no
        // live permission promise left to reject. Persist the dismissal so the
        // request is not re-derived as pending from the run log later.
        this.cloudPermissionRequestIds.delete(toolCallId);
        await this.persistCloudPermissionResolution(
          session.taskId,
          permission?.taskRunId ?? session.taskRunId,
          toolCallId,
          cloudRequestId,
          "cancelled",
        );
        return;
      }
      if (session.isCloud && cloudRequestId) {
        this.cloudPermissionRequestIds.delete(toolCallId);
        await this.sendCloudCommand(session, "permission_response", {
          requestId: cloudRequestId,
          optionId: "reject_with_feedback",
          customInput: "User cancelled the permission request.",
        });
        this.markCloudPermissionResponded(cloudRequestId);
      } else {
        await this.d.trpc.agent.cancelPermission.mutate({
          taskRunId: session.taskRunId,
          toolCallId,
        });
      }

      this.d.log.info("Permission cancelled", {
        taskId,
        toolCallId,
        isCloud: !!cloudRequestId,
      });
    } catch (error) {
      this.d.log.error("Failed to cancel permission", {
        taskId,
        toolCallId,
        error,
      });
    }
  }

  // --- Config Option Changes (Optimistic Updates) ---

  /**
   * Set a session configuration option with optimistic update and rollback.
   * This is the unified method for model, mode, thought level, etc.
   */
  async setSessionConfigOption(
    taskId: string,
    configId: string,
    value: string,
  ): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;

    // Find the config option and save previous value for rollback
    const configOptions = session.configOptions ?? [];
    const optionIndex = configOptions.findIndex((opt) => opt.id === configId);
    if (optionIndex === -1) {
      this.d.log.warn("Config option not found", { taskId, configId });
      return;
    }

    const previousValue = configOptions[optionIndex].currentValue;

    // Skip if value is already set — avoids expensive IPC round-trip (e.g. setModel ~2s)
    if (previousValue === value) {
      return;
    }

    // Optimistic update
    const updatedOptions = configOptions.map((opt) =>
      opt.id === configId
        ? ({ ...opt, currentValue: value } as SessionConfigOption)
        : opt,
    );
    this.d.store.updateSession(session.taskRunId, {
      configOptions: updatedOptions,
    });
    this.d.setPersistedConfigOptions(session.taskRunId, updatedOptions);

    if (
      !session.isCloud &&
      (session.idleKilled ||
        session.status === "disconnected" ||
        session.status === "connecting")
    ) {
      return;
    }

    try {
      if (session.isCloud) {
        await this.sendCloudCommand(session, "set_config_option", {
          configId,
          value,
        });
      } else {
        await this.d.trpc.agent.setConfigOption.mutate({
          sessionId: session.taskRunId,
          configId,
          value,
        });
      }
    } catch (error) {
      const latestConfigOptions =
        this.d.store.getSessionByTaskId(taskId)?.configOptions ?? [];
      const latestOption = latestConfigOptions.find(
        (option) => option.id === configId,
      );
      if (latestOption?.currentValue === value) {
        const rolledBackOptions = latestConfigOptions.map((option) =>
          option.id === configId
            ? ({
                ...option,
                currentValue: previousValue,
              } as SessionConfigOption)
            : option,
        );
        this.d.store.updateSession(session.taskRunId, {
          configOptions: rolledBackOptions,
        });
        this.d.setPersistedConfigOptions(session.taskRunId, rolledBackOptions);
      }
      this.d.log.error("Failed to set session config option", {
        taskId,
        configId,
        value,
        error,
      });
      this.d.toast.error("Failed to change setting. Please try again.");
    }
  }

  /**
   * Set a session configuration option by category (e.g., "mode", "model").
   * This is a convenience method that looks up the config ID by category.
   */
  async setSessionConfigOptionByCategory(
    taskId: string,
    category: string,
    value: string,
  ): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;

    const configOption = getConfigOptionByCategory(
      session.configOptions,
      category,
    );
    if (!configOption) {
      this.d.log.warn("Config option not found for category", {
        taskId,
        category,
      });
      return;
    }

    if (configOption.currentValue !== value) {
      this.d.track(ANALYTICS_EVENTS.SESSION_CONFIG_CHANGED, {
        task_id: taskId,
        category,
        from_value: String(configOption.currentValue),
        to_value: value,
      });
    }

    await this.setSessionConfigOption(taskId, configOption.id, value);
  }

  /**
   * Start a user shell execute event (shows command as running).
   * Call completeUserShellExecute with the same id when the command finishes.
   */
  async startUserShellExecute(
    taskId: string,
    id: string,
    command: string,
    cwd: string,
  ): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;

    const event = createUserShellExecuteEvent(command, cwd, undefined, id);
    this.d.store.appendEvents(session.taskRunId, [event]);
  }

  /**
   * Complete a user shell execute event with results.
   * Must be called after startUserShellExecute with the same id.
   */
  async completeUserShellExecute(
    taskId: string,
    id: string,
    command: string,
    cwd: string,
    result: { stdout: string; stderr: string; exitCode: number },
  ): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;

    const storedEntry: StoredLogEntry = {
      type: "notification",
      timestamp: new Date().toISOString(),
      notification: {
        method: "_array/user_shell_execute",
        params: { id, command, cwd, result },
      },
    };

    const event = createUserShellExecuteEvent(command, cwd, result, id);

    await this.appendAndPersist(taskId, session, event, storedEntry);
  }

  /**
   * Retry connecting to the existing session (resume attempt using
   * the sessionId from logs). Does NOT tear down — avoids the connect
   * effect loop.
   *
   * If the session failed before any conversation started (has an
   * initialPrompt saved from the original creation attempt, and no
   * conversation in memory or in the run log), creates a fresh session
   * and re-sends the prompt instead of reconnecting to an empty session.
   */
  async clearSessionError(taskId: string, repoPath: string): Promise<void> {
    this.localRepoPaths.set(taskId, repoPath);
    const session = this.d.store.getSessionByTaskId(taskId);
    if (
      session?.initialPrompt?.length &&
      !(await this.runHasConversationHistory(session))
    ) {
      const {
        taskTitle,
        initialPrompt,
        executionMode,
        adapter,
        model,
        reasoningLevel,
      } = session;
      await this.teardownSession(session.taskRunId);
      const authStatus = await this.getAuthCredentialsStatus();
      if (authStatus.kind === "restoring") {
        throw new Error("Authentication is still restoring. Please wait.");
      }
      if (authStatus.kind !== "ready") {
        throw new Error(
          "Unable to reach server. Please check your connection.",
        );
      }
      await this.createNewLocalSession(
        taskId,
        taskTitle,
        repoPath,
        authStatus.auth,
        initialPrompt,
        executionMode,
        adapter,
        model,
        reasoningLevel,
      );
      return;
    }
    await this.reconnectInPlace(taskId, repoPath);
  }

  /**
   * Whether the run already holds conversation beyond the user's prompt
   * echoes. A set `initialPrompt` alone doesn't prove the conversation never
   * started: it is only cleared when a live agent event arrives, so it
   * survives when the event subscription drops before the first agent event
   * while the agent keeps working and logging, and error sessions carry it
   * forward. Recreating the run in that state orphans the populated run log
   * behind a fresh latest_run — the task's entire history disappears — so
   * check the in-memory transcript first and fall back to the persisted log.
   */
  private async runHasConversationHistory(
    session: AgentSession,
  ): Promise<boolean> {
    const isPromptEcho = (event: AcpMessage): boolean =>
      isJsonRpcRequest(event.message) &&
      event.message.method === "session/prompt";
    if (session.events.some((event) => !isPromptEcho(event))) {
      return true;
    }
    const { rawEntries } = await this.fetchSessionLogs(
      session.logUrl,
      session.taskRunId,
    );
    return convertStoredEntriesToEvents(rawEntries).some(
      (event) => !isPromptEcho(event),
    );
  }

  /**
   * Start a fresh session for a task, abandoning the old conversation.
   * Clears the backend sessionId so the next reconnect creates a new
   * session instead of attempting to resume the stale one.
   */
  async resetSession(taskId: string, repoPath: string): Promise<void> {
    this.localRepoPaths.set(taskId, repoPath);
    await this.reconnectInPlace(taskId, repoPath, null);
  }

  /**
   * Cancel the current backend agent and reconnect under the same taskRunId.
   * Does NOT remove the session from the store (avoids connect effect loop).
   * Overwrites the store session in place via reconnectToLocalSession.
   *
   * @param overrideSessionId - Controls which sessionId is used for reconnect:
   *   - `undefined` (default): use the sessionId from logs (resume attempt)
   *   - `null`: strip the sessionId so the backend creates a fresh session
   *   - `string`: use that specific sessionId
   */
  private async reconnectInPlace(
    taskId: string,
    repoPath: string,
    overrideSessionId?: string | null,
  ): Promise<boolean> {
    this.localRepoPaths.set(taskId, repoPath);
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return false;

    const { taskRunId, taskTitle, logUrl } = session;

    // Cancel lingering backend agent (ignore errors — it may not exist
    // after a failed reconnect)
    try {
      await this.d.trpc.agent.cancel.mutate({ sessionId: taskRunId });
    } catch {
      // expected when backend has no session
    }
    this.unsubscribeFromChannel(taskRunId);

    const authStatus = await this.getAuthCredentialsStatus();
    if (authStatus.kind === "restoring") {
      throw new Error("Authentication is still restoring. Please wait.");
    }
    if (authStatus.kind !== "ready") {
      throw new Error("Unable to reach server. Please check your connection.");
    }
    const auth = authStatus.auth;

    const prefetchedLogs = await this.fetchSessionLogs(logUrl, taskRunId);

    // Determine sessionId: undefined = use from logs, null = strip (fresh), string = use as-is
    const sessionId =
      overrideSessionId === null
        ? undefined
        : (overrideSessionId ?? prefetchedLogs.sessionId);

    return this.reconnectToLocalSession(
      taskId,
      taskRunId,
      taskTitle,
      logUrl,
      repoPath,
      auth,
      { ...prefetchedLogs, sessionId },
    );
  }

  /**
   * Fetch model/effort options from the main-process preview-config endpoint
   * and merge them into the cloud session's configOptions. Cached per
   * (apiHost, adapter) so repeated visits don't refetch.
   *
   * Runs fire-and-forget: the session stays usable with just the `mode` option
   * if the fetch fails or is still in flight.
   */
  private async fetchAndApplyCloudPreviewOptions(
    taskRunId: string,
    apiHost: string,
    adapter: Adapter,
    initialModel?: string,
    initialReasoningEffort?: string,
  ): Promise<void> {
    const cacheKey = `${apiHost}::${adapter}`;
    let entry = this.previewConfigOptionsCache.get(cacheKey);
    if (!entry || Date.now() - entry.fetchedAt > 300_000) {
      if (entry) this.previewConfigOptionsCache.delete(cacheKey);
      const promise = this.d.trpc.agent.getPreviewConfigOptions
        .query({ apiHost, adapter })
        .catch((err: unknown) => {
          this.d.log.warn(
            "Failed to fetch preview config options for cloud session",
            {
              apiHost,
              adapter,
              error: err,
            },
          );
          // Only evict if this entry is still the cached one; a concurrent
          // refresh may have replaced it and we must not drop the fresh entry.
          if (this.previewConfigOptionsCache.get(cacheKey) === entry) {
            this.previewConfigOptionsCache.delete(cacheKey);
          }
          return [] as SessionConfigOption[];
        });
      entry = { promise, fetchedAt: Date.now() };
      this.previewConfigOptionsCache.set(cacheKey, entry);
    }

    const previewOptions = await entry.promise;
    const session = this.d.store.getSessions()[taskRunId];
    if (!session || session.adapter !== adapter) return;

    const existingOptions = session.configOptions ?? [];
    const existingModelOption = getConfigOptionByCategory(
      existingOptions,
      "model",
    );
    const existingReasoningOption = getConfigOptionByCategory(
      existingOptions,
      "thought_level",
    );
    const existingModel = existingModelOption?.currentValue;
    const existingReasoningEffort = existingReasoningOption?.currentValue;
    const preferredModel =
      typeof existingModel === "string" ? existingModel : initialModel;
    const preferredReasoningEffort =
      typeof existingReasoningEffort === "string"
        ? existingReasoningEffort
        : initialReasoningEffort;
    const applyPreferredValue = (
      option: SessionConfigOption,
      preferredValue: string | undefined,
      existingOption: SessionConfigOption | undefined,
    ): SessionConfigOption => {
      if (option.type !== "select" || !preferredValue) return option;

      const previewValues = flattenSelectOptions(option.options);
      if (previewValues.some((value) => value.value === preferredValue)) {
        return { ...option, currentValue: preferredValue };
      }

      const existingValues =
        existingOption?.type === "select"
          ? flattenSelectOptions(existingOption.options)
          : [];
      const reasoningLabels: Record<string, string> = {
        low: "Low",
        medium: "Medium",
        high: "High",
        xhigh: "Extra High",
        max: "Max",
      };
      const selectedValue = existingValues.find(
        (value) => value.value === preferredValue,
      ) ?? {
        value: preferredValue,
        name:
          option.category === "thought_level"
            ? (reasoningLabels[preferredValue] ?? preferredValue)
            : preferredValue,
      };

      if (option.options.length > 0 && "group" in option.options[0]) {
        return {
          ...option,
          currentValue: preferredValue,
          options: [
            ...(option.options as SessionConfigSelectGroup[]),
            {
              group: "selected",
              name: "Selected",
              options: [selectedValue],
            },
          ],
        };
      }

      return {
        ...option,
        currentValue: preferredValue,
        options: [
          ...(option.options as SessionConfigSelectOption[]),
          selectedValue,
        ],
      };
    };
    const extras = previewOptions
      .filter(
        (opt) => opt.category === "model" || opt.category === "thought_level",
      )
      .map((opt) => {
        if (opt.category === "model") {
          return applyPreferredValue(opt, preferredModel, existingModelOption);
        }
        if (opt.category === "thought_level") {
          return applyPreferredValue(
            opt,
            preferredReasoningEffort,
            existingReasoningOption,
          );
        }
        return opt;
      });

    if (extras.length === 0) return;

    const previewCategories = new Set(extras.map((option) => option.category));
    const merged = [
      ...existingOptions.filter(
        (option) => !previewCategories.has(option.category),
      ),
      ...extras,
    ];

    if (JSON.stringify(existingOptions) === JSON.stringify(merged)) return;

    this.d.store.updateSession(taskRunId, { configOptions: merged });
  }

  /**
   * Start watching a cloud task via main-process CloudTaskService.
   *
   * The watcher stays alive across navigation. A fresh watcher is created only
   * on first visit or when the runId changes (new run started). Terminal
   * status triggers full teardown from within handleCloudTaskUpdate via
   * stopCloudTaskWatch().
   */
  /**
   * Register this client as the relay executor for a run's desktop-only MCP
   * servers (docs/cloud-mcp-relay.md). Called by the creation saga — only the
   * creating client may execute relay requests.
   */
  async designateRelayedMcpServers(
    runId: string,
    servers: string[],
  ): Promise<void> {
    if (servers.length === 0) return;
    await this.d.trpc.cloudTask.designateRelayedMcpServers.mutate({
      runId,
      servers,
    });
  }

  watchCloudTask(
    taskId: string,
    runId: string,
    apiHost: string,
    teamId: number,
    onStatusChange?: () => void,
    logUrl?: string,
    initialMode?: string,
    adapter: Adapter = "claude",
    initialModel?: string,
    taskDescription?: string,
    resumeFromEntryCount?: number,
    runStatus?: TaskRunStatus,
    initialReasoningEffort?: string,
    runState?: Record<string, unknown>,
  ): () => void {
    const taskRunId = runId;
    const persistedConfigOptions = this.d.getPersistedConfigOptions(taskRunId);
    const persistedAdapter = this.d.adapterStore.getAdapter(taskRunId);
    const buildInitialConfigOptions = (
      mode: string | undefined,
      configAdapter: Adapter | undefined = persistedAdapter,
    ): SessionConfigOption[] => {
      const defaults = addMissingCloudRuntimeConfigOptions(
        buildCloudDefaultConfigOptions(mode, adapter),
        adapter,
        initialModel,
        initialReasoningEffort,
      );
      if (!persistedConfigOptions?.length) return defaults;
      if (configAdapter && configAdapter !== adapter) return defaults;

      const defaultIds = new Set(defaults.map((option) => option.id));
      const completeOptions = [
        ...defaults,
        ...persistedConfigOptions.filter(
          (option) => !defaultIds.has(option.id),
        ),
      ];
      return mergeConfigOptions(completeOptions, persistedConfigOptions);
    };

    if (this.supersededRunIds.has(runId)) return () => {};
    this.d.adapterStore.setAdapter(taskRunId, adapter);

    const existingWatcher = this.cloudTaskWatchers.get(taskId);

    // Resuming same run — reuse the existing watcher.
    if (
      existingWatcher &&
      existingWatcher.runId === runId &&
      existingWatcher.apiHost === apiHost &&
      existingWatcher.teamId === teamId
    ) {
      if (onStatusChange) {
        existingWatcher.onStatusChange = onStatusChange;
      }
      // The run finished while a live watcher was still attached: apply the
      // final transcript, mark the terminal status, and tear the watcher down
      // instead of leaving a live stream on a dead run.
      if (isTerminalStatus(runStatus)) {
        const terminalSession = this.d.store.getSessionByTaskId(taskId);
        if (terminalSession?.taskRunId === taskRunId) {
          void this.hydrateCloudTaskSessionFromLogs(
            taskId,
            taskRunId,
            logUrl,
            taskDescription,
            runStatus,
            runState,
          );
        }
        this.finalizeTerminalCloudTask(taskRunId, runStatus);
        this.stopCloudTaskWatch(taskId);
        return () => {};
      }
      // Ensure configOptions is populated on revisit
      const existing = this.d.store.getSessionByTaskId(taskId);
      if (existing) {
        const existingMode = getConfigOptionByCategory(
          existing.configOptions,
          "mode",
        )?.currentValue;
        const currentMode =
          typeof existingMode === "string" ? existingMode : initialMode;
        const shouldRefreshConfigOptions =
          !existing.configOptions?.length || existing.adapter !== adapter;
        if (shouldRefreshConfigOptions) {
          this.d.store.updateSession(existing.taskRunId, {
            adapter,
            configOptions: buildInitialConfigOptions(
              currentMode,
              existing.adapter,
            ),
          });
        } else {
          const configOptions = addMissingCloudRuntimeConfigOptions(
            existing.configOptions ?? [],
            adapter,
            initialModel,
            initialReasoningEffort,
          );
          if (configOptions !== existing.configOptions) {
            this.d.store.updateSession(existing.taskRunId, { configOptions });
          }
        }
        void this.fetchAndApplyCloudPreviewOptions(
          existing.taskRunId,
          apiHost,
          adapter,
          initialModel,
          initialReasoningEffort,
        );
      }
      if (
        typeof runState?.resume_from_run_id === "string" &&
        !this.pendingPermissionHydratedRuns.has(taskRunId)
      ) {
        void this.hydrateResumeCloudTaskSessionFromLogs(
          taskId,
          taskRunId,
          logUrl,
          taskDescription,
          runStatus,
          runState,
        );
      }
      return () => {};
    }

    // An already-finished run we've already hydrated has no live stream to
    // attach to: the snapshot in the store is the complete, final conversation.
    // Re-watching it refetches the same logs, immediately stops again on the
    // terminal snapshot, and that snapshot rewrites session.configOptions,
    // which re-fires the reconcile effect and spins a start/stop loop. Skip it.
    // Gated on no live watcher: a stale watcher for a different run still needs
    // the stop-and-restart below.
    if (!existingWatcher) {
      const hydrated = this.d.store.getSessionByTaskId(taskId);
      const needsPersistedPermissionHydration =
        hydrated?.taskRunId === taskRunId &&
        hydrated.pendingPermissions.size === 0 &&
        !this.pendingPermissionHydratedRuns.has(taskRunId);
      if (
        hydrated?.taskRunId === taskRunId &&
        isTerminalStatus(hydrated.cloudStatus) &&
        hydrated.processedLineCount !== undefined
      ) {
        if (needsPersistedPermissionHydration) {
          this.hydrateCloudTaskSessionFromLogs(
            taskId,
            taskRunId,
            logUrl,
            taskDescription,
            runStatus,
            runState,
          );
        }
        return () => {};
      }
    }

    // Different run — full cleanup of old watcher first
    if (existingWatcher) {
      this.stopCloudTaskWatch(taskId);
    }

    const startToken = ++this.nextCloudTaskWatchToken;

    // Create session in the store
    const existing = this.d.store.getSessionByTaskId(taskId);
    // A same-run session with history but no processedLineCount came from a
    // non-cloud hydration path. Reset it so the cloud snapshot becomes the
    // single source of truth instead of being appended on top.
    const shouldResetExistingSession =
      existing?.taskRunId === taskRunId &&
      existing.events.length > 0 &&
      existing.processedLineCount === undefined;
    const shouldHydratePersistedPermissions =
      existing?.taskRunId === taskRunId &&
      existing.pendingPermissions.size === 0 &&
      existing.processedLineCount !== undefined &&
      !this.pendingPermissionHydratedRuns.has(taskRunId) &&
      (isTerminalStatus(existing.cloudStatus) ||
        (runStatus !== undefined && isTerminalStatus(runStatus)));
    const shouldHydrateResumeChain =
      Boolean(runState?.resume_from_run_id) &&
      !this.pendingPermissionHydratedRuns.has(taskRunId);
    const shouldHydrateSession =
      !existing ||
      existing.taskRunId !== taskRunId ||
      shouldResetExistingSession ||
      existing.events.length === 0 ||
      shouldHydratePersistedPermissions ||
      shouldHydrateResumeChain;

    if (
      !existing ||
      existing.taskRunId !== taskRunId ||
      shouldResetExistingSession
    ) {
      const taskTitle = existing?.taskTitle ?? "Cloud Task";
      const session = createBaseSession(taskRunId, taskId, taskTitle);
      session.status = "disconnected";
      session.isCloud = true;
      session.adapter = adapter;
      session.configOptions = buildInitialConfigOptions(
        initialMode,
        existing?.taskRunId === taskRunId ? existing.adapter : persistedAdapter,
      );
      this.d.store.setSession(session);
      // Optimistic seeding for the initial task description is deferred
      // until `hydrateCloudTaskSessionFromLogs` confirms there's no prior
      // conversation. Otherwise reopening a task with history would flash
      // the description at top until hydration replaced it.
    } else {
      // Ensure cloud flag and configOptions are set on existing sessions
      const updates: Partial<AgentSession> = {};
      if (!existing.isCloud) updates.isCloud = true;
      if (existing.adapter !== adapter) updates.adapter = adapter;
      if (!existing.configOptions?.length || existing.adapter !== adapter) {
        const existingMode = getConfigOptionByCategory(
          existing.configOptions,
          "mode",
        )?.currentValue;
        const currentMode =
          typeof existingMode === "string" ? existingMode : initialMode;
        updates.configOptions = buildInitialConfigOptions(
          currentMode,
          existing.adapter,
        );
      } else {
        const configOptions = addMissingCloudRuntimeConfigOptions(
          existing.configOptions,
          adapter,
          initialModel,
          initialReasoningEffort,
        );
        if (configOptions !== existing.configOptions) {
          updates.configOptions = configOptions;
        }
      }
      if (Object.keys(updates).length > 0) {
        this.d.store.updateSession(existing.taskRunId, updates);
      }
    }

    void this.fetchAndApplyCloudPreviewOptions(
      taskRunId,
      apiHost,
      adapter,
      initialModel,
      initialReasoningEffort,
    );

    // A run that is already terminal has no live stream to subscribe to:
    // hydrate the final transcript, settle the terminal status, and return
    // without registering a watcher. Plain hydration already fetches the
    // full resume chain for terminal runs, and the resume wrapper only
    // exists to buffer a live stream that does not exist here.
    if (isTerminalStatus(runStatus)) {
      void this.hydrateCloudTaskSessionFromLogs(
        taskId,
        taskRunId,
        logUrl,
        taskDescription,
        runStatus,
        runState,
      );
      this.finalizeTerminalCloudTask(taskRunId, runStatus);
      return () => {};
    }

    const processCloudUpdate = (update: CloudTaskUpdatePayload): void => {
      if (update.kind === "logs" || update.kind === "snapshot") {
        this.d.store.updateSession(taskRunId, {
          cloudTranscriptEntryCount: update.totalEntryCount,
        });
      }
      const watcher = this.cloudTaskWatchers.get(taskId);
      const resumeHistoryCountOffset =
        watcher?.runId === runId ? (watcher.resumeHistoryCountOffset ?? 0) : 0;
      const normalizedUpdate: CloudTaskUpdatePayload =
        resumeHistoryCountOffset > 0 &&
        (update.kind === "logs" || update.kind === "snapshot")
          ? {
              ...update,
              totalEntryCount: Math.max(
                0,
                update.totalEntryCount - resumeHistoryCountOffset,
              ),
            }
          : update;
      // Evaluate staleness before handleCloudTaskUpdate mutates cloudStatus:
      // a late non-terminal update must not re-notify after the run settled.
      const isStaleNonTerminalStatus = this.isStaleNonTerminalCloudUpdate(
        taskRunId,
        normalizedUpdate,
      );
      this.handleCloudTaskUpdate(taskRunId, normalizedUpdate);
      if (
        (update.kind === "status" ||
          update.kind === "snapshot" ||
          update.kind === "error") &&
        !isStaleNonTerminalStatus &&
        watcher?.onStatusChange
      ) {
        watcher.onStatusChange();
      }
    };

    const watcher: CloudTaskWatcher = {
      runId,
      apiHost,
      teamId,
      startToken,
      resumeFromEntryCount,
      resumeHistoryCountOffset: shouldHydrateResumeChain
        ? resumeFromEntryCount
        : 0,
      resumeHydrationToken: 0,
      bufferResumeUpdates: false,
      bufferedResumeUpdates: [],
      processCloudUpdate,
      subscription: { unsubscribe: () => undefined },
      onStatusChange,
    };
    this.cloudTaskWatchers.set(taskId, watcher);

    // Subscribe before starting the main-process watcher so the first replayed
    // SSE/log burst cannot race ahead of the renderer subscription.
    watcher.subscription = this.d.trpc.cloudTask.onUpdate.subscribe(
      { taskId, runId },
      {
        onData: (update: CloudTaskUpdatePayload) => {
          const activeWatcher = this.cloudTaskWatchers.get(taskId);
          if (!activeWatcher || activeWatcher.runId !== runId) {
            return;
          }
          if (activeWatcher.bufferResumeUpdates) {
            activeWatcher.bufferedResumeUpdates.push(update);
            return;
          }
          activeWatcher.processCloudUpdate(update);
        },
        onError: (err: unknown) =>
          this.d.log.error("Cloud task subscription error", { taskId, err }),
      },
    );

    if (shouldHydrateSession) {
      if (shouldHydrateResumeChain) {
        void this.hydrateResumeCloudTaskSessionFromLogs(
          taskId,
          taskRunId,
          logUrl,
          taskDescription,
          runStatus,
          runState,
        );
      } else {
        void this.hydrateCloudTaskSessionFromLogs(
          taskId,
          taskRunId,
          logUrl,
          taskDescription,
          runStatus,
          runState,
        );
      }
    }

    // Start main-process watcher after the subscription is attached.
    void (async () => {
      try {
        if (!this.isCurrentCloudTaskWatcher(taskId, runId, startToken)) {
          return;
        }

        await this.d.trpc.cloudTask.watch.mutate({
          taskId,
          runId,
          apiHost,
          teamId,
          resumeFromEntryCount,
        });

        // If the local watcher was torn down while the watch request was in
        // flight, send a compensating unwatch after the start request lands.
        if (!this.isCurrentCloudTaskWatcher(taskId, runId, startToken)) {
          await this.d.trpc.cloudTask.unwatch.mutate({ taskId, runId });
        }
      } catch (err: unknown) {
        if (!this.isCurrentCloudTaskWatcher(taskId, runId, startToken)) {
          return;
        }
        this.d.log.warn("Failed to start cloud task watcher", { taskId, err });
      }
    })();

    return () => {};
  }

  /**
   * Stash the initial cloud prompt (user message plus any channel CONTEXT.md
   * block) so the optimistic placeholder can render it — and its CONTEXT.md
   * chip — immediately, instead of waiting for the sandbox to boot and echo it
   * back. Best-effort: lost on reload, where the merge layer dedupes the echo
   * against the bare placeholder instead.
   */
  rememberInitialCloudPrompt(taskId: string, content: string): void {
    const trimmed = content.trim();
    if (trimmed) {
      this.initialCloudOptimisticPrompt.set(taskId, content);
    }
  }

  private hydrateCloudTaskSessionFromLogs(
    taskId: string,
    taskRunId: string,
    logUrl?: string,
    taskDescription?: string,
    runStatus?: TaskRunStatus,
    runState?: Record<string, unknown>,
  ): Promise<CloudHydrationResult | undefined> {
    // Key by hydration mode, not just run: a run going terminal must start
    // its final-transcript hydration even while a resume-chain or single-run
    // hydration for the same run is still in flight.
    const hydrationMode = isTerminalStatus(runStatus)
      ? "terminal-chain"
      : runState?.resume_from_run_id
        ? "resume-chain"
        : "single";
    const hydrationKey = `${taskRunId}:${hydrationMode}`;
    const existing = this.cloudHydrationPromises.get(hydrationKey);
    if (existing) {
      return existing;
    }
    const hydration = this.performCloudTaskSessionHydration(
      taskId,
      taskRunId,
      logUrl,
      taskDescription,
      runStatus,
      runState,
    ).catch((err: unknown) => {
      this.d.log.warn("Failed to hydrate cloud task session from logs", {
        taskId,
        taskRunId,
        err,
      });
      return undefined;
    });
    this.cloudHydrationPromises.set(hydrationKey, hydration);
    void hydration.finally(() => {
      if (this.cloudHydrationPromises.get(hydrationKey) === hydration) {
        this.cloudHydrationPromises.delete(hydrationKey);
      }
    });
    return hydration;
  }

  private async hydrateResumeCloudTaskSessionFromLogs(
    taskId: string,
    taskRunId: string,
    logUrl?: string,
    taskDescription?: string,
    runStatus?: TaskRunStatus,
    runState?: Record<string, unknown>,
  ): Promise<void> {
    const watcher = this.cloudTaskWatchers.get(taskId);
    if (!watcher || watcher.runId !== taskRunId) return;
    const hydrationToken = ++watcher.resumeHydrationToken;
    watcher.bufferResumeUpdates = true;

    const result = await this.hydrateCloudTaskSessionFromLogs(
      taskId,
      taskRunId,
      logUrl,
      taskDescription,
      runStatus,
      runState,
    );
    const activeWatcher = this.cloudTaskWatchers.get(taskId);
    if (
      !activeWatcher ||
      activeWatcher.runId !== taskRunId ||
      activeWatcher.resumeHydrationToken !== hydrationToken
    ) {
      return;
    }

    this.applyResumeHydrationOffset(taskId, taskRunId, result);
    activeWatcher.bufferResumeUpdates = false;
    const bufferedUpdates = activeWatcher.bufferedResumeUpdates.splice(0);
    for (const update of bufferedUpdates) {
      activeWatcher.processCloudUpdate(update);
    }
  }

  private applyResumeHydrationOffset(
    taskId: string,
    taskRunId: string,
    result: CloudHydrationResult | undefined,
  ): void {
    if (!result) return;
    const watcher = this.cloudTaskWatchers.get(taskId);
    if (!watcher || watcher.runId !== taskRunId) return;
    watcher.resumeHistoryCountOffset = Math.max(
      0,
      result.historyEntryCount - result.liveStreamLineCount,
    );
  }

  private async performCloudTaskSessionHydration(
    taskId: string,
    taskRunId: string,
    logUrl?: string,
    taskDescription?: string,
    runStatus?: TaskRunStatus,
    runState?: Record<string, unknown>,
  ): Promise<CloudHydrationResult | undefined> {
    let rawEntries: StoredLogEntry[];
    let liveStreamLineCount: number;
    let resumeLeafEntryStartIndex: number | undefined;
    const resumeFromRunId =
      typeof runState?.resume_from_run_id === "string"
        ? runState.resume_from_run_id
        : undefined;
    const isResumeRun = Boolean(resumeFromRunId);
    const isTerminalRun = isTerminalStatus(runStatus);
    if (isTerminalRun || isResumeRun) {
      // Resume chains need the full history even while the leaf run is still
      // active; otherwise a renderer restart hydrates only the final run.
      // Non-resume in-progress runs keep using the single-run log so hydrate
      // cannot race the live stream and double the active turn.
      const authStatus = await this.getAuthCredentialsStatus();
      if (authStatus.kind !== "ready") {
        return;
      }
      if (resumeFromRunId) {
        if (isTerminalStatus(runStatus)) {
          const result =
            await authStatus.auth.client.getTaskRunSessionLogsResult(
              taskId,
              taskRunId,
              { limit: 100000 },
            );
          if (!result.complete) {
            this.d.log.warn("Resume session log hydration was incomplete", {
              taskId,
              taskRunId,
              resumeFromRunId,
            });
            return;
          }
          rawEntries = result.entries;
          const markedLeafStart = rawEntries.findIndex(
            (entry) => getEntryTaskRunMarker(entry) === taskRunId,
          );
          resumeLeafEntryStartIndex =
            markedLeafStart >= 0 ? markedLeafStart : undefined;
          liveStreamLineCount =
            markedLeafStart >= 0
              ? rawEntries.length - markedLeafStart
              : rawEntries.length;
        } else {
          const [ancestorResult, currentRunResult] = await Promise.all([
            authStatus.auth.client.getTaskRunSessionLogsResult(
              taskId,
              resumeFromRunId,
              { limit: 100000 },
            ),
            authStatus.auth.client.getTaskRunSessionLogsResult(
              taskId,
              taskRunId,
              { limit: 100000 },
            ),
          ]);
          if (!ancestorResult.complete || !currentRunResult.complete) {
            this.d.log.warn("Resume session log hydration was incomplete", {
              taskId,
              taskRunId,
              resumeFromRunId,
              ancestorComplete: ancestorResult.complete,
              currentRunComplete: currentRunResult.complete,
            });
            return;
          }
          const ancestorEntries: StoredLogEntry[] = ancestorResult.entries;
          const currentRunEntries: StoredLogEntry[] = currentRunResult.entries;
          const ancestorKeys = ancestorEntries.map((entry) =>
            JSON.stringify(entry),
          );
          const currentKeys = currentRunEntries.map((entry) =>
            JSON.stringify(entry),
          );
          const overlap = suffixPrefixOverlap(ancestorKeys, currentKeys);
          const persistedLeafEntries = currentRunEntries.slice(overlap);
          const leafLogs = await this.fetchSessionLogs(logUrl, taskRunId);
          const leafKeys = new Set(
            persistedLeafEntries.map((entry) => JSON.stringify(entry)),
          );
          rawEntries = [
            ...ancestorEntries,
            ...persistedLeafEntries,
            ...leafLogs.rawEntries.filter(
              (entry) => !leafKeys.has(JSON.stringify(entry)),
            ),
          ];
          resumeLeafEntryStartIndex = ancestorEntries.length;
          liveStreamLineCount = Math.max(
            leafLogs.totalLineCount,
            persistedLeafEntries.length,
          );
        }
      } else {
        const result = await authStatus.auth.client.getTaskRunSessionLogsResult(
          taskId,
          taskRunId,
          { limit: 100000 },
        );
        if (!result.complete) {
          this.d.log.warn("Session log hydration was incomplete", {
            taskId,
            taskRunId,
          });
          return;
        }
        rawEntries = result.entries;
        liveStreamLineCount = rawEntries.length;
        // A terminal run whose persisted chain comes back empty can still
        // have a complete S3 session log (persistence raced teardown); fall
        // back to it rather than hydrating an empty final transcript.
        if (rawEntries.length === 0 && logUrl) {
          const parsed = await this.fetchSessionLogs(logUrl, taskRunId);
          if (parsed.rawEntries.length > 0) {
            rawEntries = parsed.rawEntries;
            liveStreamLineCount = parsed.totalLineCount;
          }
        }
      }
    } else {
      const parsed = await this.fetchSessionLogs(logUrl, taskRunId);
      rawEntries = parsed.rawEntries;
      liveStreamLineCount = parsed.totalLineCount;
    }

    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session || session.taskRunId !== taskRunId) {
      return;
    }

    let events = convertStoredEntriesToEvents(rawEntries, undefined, {
      taskRunId,
      startEntryIndex: 0,
      firstPositionedEntryIndex: resumeLeafEntryStartIndex,
    });
    if (isResumeRun && session.events.length > 0) {
      const inheritedEvents = reconcileLiveEventsWithHydratedEvents(
        session.events,
        events,
      );
      events = [...events, ...inheritedEvents];
      const watcher = this.cloudTaskWatchers.get(taskId);
      const hasLeafLocalWatcherCursor =
        watcher?.runId === taskRunId &&
        watcher.resumeHistoryCountOffset !== undefined;
      if (hasLeafLocalWatcherCursor) {
        liveStreamLineCount = Math.max(
          liveStreamLineCount,
          session.processedLineCount ?? 0,
        );
      }
    }
    const hasUserPrompt = events.some(
      (e: AcpMessage) =>
        isJsonRpcRequest(e.message) && e.message.method === "session/prompt",
    );

    // Seed the optimistic user-message bubble whenever the agent has
    // not yet recorded an initial `session/prompt` request — covers the
    // brand-new task case as well as "agent has emitted lifecycle
    // notifications but hasn't received its first prompt yet". Prefer the
    // stashed initial prompt (which carries the channel CONTEXT.md block, so
    // its chip renders right away) over the bare task description.
    const seedContent =
      this.initialCloudOptimisticPrompt.get(taskId) ?? taskDescription;
    if (!isTerminalRun && !hasUserPrompt && seedContent?.trim()) {
      this.d.store.appendOptimisticItem(taskRunId, {
        type: "user_message",
        content: seedContent,
        timestamp: Date.now(),
      });
    }
    if (hasUserPrompt || isTerminalRun) {
      // The stash is no longer needed once the real prompt lands - and a
      // finished run gets no further echoes, so leftover optimistic items
      // would otherwise linger as phantom tail items on the final transcript.
      this.initialCloudOptimisticPrompt.delete(taskId);
      this.d.store.clearTailOptimisticItems(taskRunId);
    }

    if (rawEntries.length === 0) {
      this.pendingPermissionHydratedRuns.add(taskRunId);
      return {
        historyEntryCount: 0,
        liveStreamLineCount,
      };
    }

    // If live updates already populated a processed count, don't overwrite
    // that newer state with the persisted baseline fetched during startup.
    // Terminal hydration is different: it is the final transcript, so apply
    // it whenever the persisted chain has more lines than the local stream.
    const effectiveLineCount = Math.max(liveStreamLineCount, rawEntries.length);
    const alreadyApplied = isTerminalRun
      ? (session.processedLineCount ?? 0) >= effectiveLineCount
      : session.processedLineCount !== undefined &&
        session.processedLineCount > 0 &&
        !isResumeRun;
    if (alreadyApplied) {
      this.surfacePersistedPendingPermissions(taskRunId, rawEntries);
      this.pendingPermissionHydratedRuns.add(taskRunId);
      return {
        historyEntryCount: rawEntries.length,
        liveStreamLineCount: session.processedLineCount ?? liveStreamLineCount,
      };
    }

    // A concurrent terminal-chain hydration (they memoize under different
    // mode keys) may have already recorded the full chain as processed; a
    // leaf-stream cursor from this older hydration must never lower it once
    // the run has settled.
    const settled = this.d.store.getSessions()[taskRunId];
    const settledCursor = isTerminalStatus(settled?.cloudStatus)
      ? (settled?.processedLineCount ?? 0)
      : 0;

    this.d.store.updateSession(taskRunId, {
      events,
      isCloud: true,
      logUrl: logUrl ?? session.logUrl,
      cloudTranscriptEntryCount: rawEntries.length,
      // Terminal hydration records the whole chain as processed so nothing
      // re-applies it; live resume runs keep the leaf-stream cursor.
      processedLineCount: isTerminalRun
        ? effectiveLineCount
        : Math.max(liveStreamLineCount, settledCursor),
    });
    this.surfacePersistedPendingPermissions(taskRunId, rawEntries);
    this.pendingPermissionHydratedRuns.add(taskRunId);
    // Without this the "Galumphing…" indicator stays hidden when the hydrated
    // baseline already contains an in-flight session/prompt — the live delta
    // path otherwise sees delta <= 0 and never re-evaluates the tail.
    this.updatePromptStateFromEvents(taskRunId, events);
    if (isTerminalRun) {
      this.clearTerminalCloudPromptState(taskRunId);
    }
    return {
      historyEntryCount: rawEntries.length,
      liveStreamLineCount,
    };
  }

  private finalizeTerminalCloudTask(
    taskRunId: string,
    status: TaskRunStatus | undefined,
  ): void {
    this.d.store.updateCloudStatus(taskRunId, { status });
    this.clearTerminalCloudPromptState(taskRunId);
  }

  /**
   * A terminal run can never flush its queue or answer a pending prompt;
   * leaving those set keeps the composer in a busy state forever.
   */
  private clearTerminalCloudPromptState(taskRunId: string): void {
    const session = this.d.store.getSessions()[taskRunId];
    if (
      !session ||
      (!session.isPromptPending && session.messageQueue.length === 0)
    ) {
      return;
    }

    this.d.store.clearMessageQueue(session.taskId);
    this.d.store.updateSession(taskRunId, {
      isPromptPending: false,
    });
  }

  /**
   * SSE replays and out-of-order bursts can deliver a non-terminal status
   * after the run already settled; applying it would revive a finished run.
   */
  private isStaleNonTerminalCloudUpdate(
    taskRunId: string,
    update: CloudTaskUpdatePayload,
  ): boolean {
    if (update.kind !== "status" && update.kind !== "snapshot") {
      return false;
    }
    if (update.status === undefined) {
      return false;
    }
    const currentCloudStatus =
      this.d.store.getSessions()[taskRunId]?.cloudStatus;
    return (
      isTerminalStatus(currentCloudStatus) && !isTerminalStatus(update.status)
    );
  }

  private isCurrentCloudTaskWatcher(
    taskId: string,
    runId: string,
    startToken: number,
  ): boolean {
    const watcher = this.cloudTaskWatchers.get(taskId);
    return watcher?.runId === runId && watcher.startToken === startToken;
  }

  /**
   * Fully stop a cloud task watcher. The tRPC subscription unwatches from the
   * main process in its finally handler; the in-flight watch path below sends a
   * compensating unwatch if teardown wins before watch.mutate lands.
   */
  stopCloudTaskWatch(taskId: string): void {
    const watcher = this.cloudTaskWatchers.get(taskId);
    if (!watcher) return;

    watcher.subscription.unsubscribe();
    this.cloudTaskWatchers.delete(taskId);
    this.cloudLogGapReconciler.forgetDeficiency(watcher.runId);
  }

  async preflightToLocal(taskId: string, repoPath: string) {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session)
      return {
        canHandoff: false as const,
        localTreeDirty: false as const,
        reason: "No session found",
      };

    const auth = await this.getHandoffAuth();
    if (!auth)
      return {
        canHandoff: false as const,
        localTreeDirty: false as const,
        reason: "Authentication required",
      };

    const preflight = await this.d.trpc.handoff.preflight.query({
      taskId,
      runId: session.taskRunId,
      repoPath,
      apiHost: auth.apiHost,
      teamId: auth.projectId,
    });

    return {
      canHandoff: preflight.canHandoff,
      localTreeDirty: preflight.localTreeDirty,
      localGitState: preflight.localGitState,
      changedFiles: preflight.changedFiles,
      reason: preflight.reason,
    };
  }

  async handoffToLocal(taskId: string, repoPath: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) {
      this.d.log.warn("No session found for handoff", { taskId });
      return;
    }

    const runId = session.taskRunId;
    const auth = await this.getHandoffAuth();
    if (!auth) return;

    this.d.store.updateSession(runId, { handoffInProgress: true });

    try {
      const preflight = await this.runHandoffPreflight(
        taskId,
        runId,
        repoPath,
        auth,
      );
      this.stopCloudTaskWatch(taskId);
      this.d.store.updateSession(runId, { status: "connecting" });
      await this.executeHandoff(
        taskId,
        runId,
        repoPath,
        auth,
        preflight.localGitState,
      );
      this.transitionToLocalSession(runId);
      this.subscribeToChannel(runId);
      await Promise.all([
        this.d.queryClient.refetchQueries({ queryKey: ["tasks"] }),
        this.d.queryClient.refetchQueries({
          queryKey: this.d.WORKSPACE_QUERY_KEY,
        }),
      ]);
      this.d.store.updateSession(runId, { handoffInProgress: false });
      this.d.log.info("Cloud-to-local handoff complete", { taskId, runId });
    } catch (err) {
      this.d.log.error("Handoff failed", { taskId, err });
      this.d.toast.error(
        err instanceof Error ? err.message : "Handoff to local failed",
      );
      this.watchCloudTask(taskId, runId, auth.apiHost, auth.projectId);
      this.d.store.updateSession(runId, {
        handoffInProgress: false,
        status: "disconnected",
      });
    }
  }

  async handoffToCloud(taskId: string, repoPath: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) {
      this.d.log.warn("No session found for cloud handoff", { taskId });
      return;
    }

    const runId = session.taskRunId;
    const auth = await this.getHandoffAuth();
    if (!auth) return;

    this.d.store.updateSession(runId, { handoffInProgress: true });

    try {
      const preflight = await this.d.trpc.handoff.preflightToCloud.query({
        taskId,
        runId,
        repoPath,
      });
      if (!preflight.canHandoff) {
        this.d.store.updateSession(runId, {
          handoffInProgress: false,
        });
        throw new Error(preflight.reason ?? "Cannot hand off to cloud");
      }

      this.unsubscribeFromChannel(runId);
      this.d.store.updateSession(runId, { status: "connecting" });

      const result = await this.d.trpc.handoff.executeToCloud.mutate({
        taskId,
        runId,
        repoPath,
        apiHost: auth.apiHost,
        teamId: auth.projectId,
        localGitState: preflight.localGitState,
      });
      if (!result.success) {
        if (result.code === GITHUB_AUTHORIZATION_REQUIRED_CODE) {
          throw new GitHubAuthorizationRequiredForCloudHandoffError(
            result.error,
          );
        }
        throw new Error(result.error ?? "Handoff to cloud failed");
      }

      this.d.store.updateSession(runId, {
        isCloud: true,
        cloudStatus: undefined,
        cloudStage: undefined,
        cloudOutput: undefined,
        cloudErrorMessage: undefined,
        cloudBranch: undefined,
        status: "disconnected",
        processedLineCount: result.logEntryCount ?? 0,
      });

      this.watchCloudTask(taskId, runId, auth.apiHost, auth.projectId);
      await Promise.all([
        this.d.queryClient.refetchQueries({ queryKey: ["tasks"] }),
        this.d.queryClient.refetchQueries({
          queryKey: this.d.WORKSPACE_QUERY_KEY,
        }),
      ]);
      this.d.store.updateSession(runId, { handoffInProgress: false });
      this.d.log.info("Local-to-cloud handoff complete", { taskId, runId });
    } catch (err) {
      this.d.log.error("Handoff to cloud failed", { taskId, err });
      if (err instanceof GitHubAuthorizationRequiredForCloudHandoffError) {
        await this.startGithubReauthForCloudHandoff(auth.projectId);
      } else {
        this.d.toast.error(
          err instanceof Error ? err.message : "Handoff to cloud failed",
        );
      }
      this.subscribeToChannel(runId);
      this.d.store.updateSession(runId, {
        handoffInProgress: false,
        status: "disconnected",
      });
    }
  }

  private async startGithubReauthForCloudHandoff(
    projectId: number,
  ): Promise<void> {
    const client = await this.d.getAuthenticatedClient();
    if (!client) {
      this.d.toast.error("Sign in before connecting GitHub.");
      return;
    }

    try {
      const { install_url: installUrl } =
        await client.startGithubUserIntegrationConnect(projectId);
      const url = installUrl?.trim();
      if (!url) {
        this.d.toast.error(
          "GitHub connection did not return a URL. Please try again.",
        );
        return;
      }

      await this.d.trpc.os.openExternal.mutate({ url });
      this.d.toast.info(
        "Connect GitHub to continue in cloud",
        "Complete the authorization in your browser, then click Continue again.",
      );
    } catch (error) {
      this.d.toast.error(
        error instanceof Error
          ? error.message
          : "Failed to start GitHub connection",
      );
    }
  }

  private async getHandoffAuth(): Promise<{
    apiHost: string;
    projectId: number;
  } | null> {
    let auth: Awaited<ReturnType<SessionServiceDeps["fetchAuthState"]>>;
    try {
      auth = await this.d.fetchAuthState();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      this.d.toast.error(`Authentication required for handoff: ${message}`);
      return null;
    }
    if (!auth.currentProjectId || !auth.cloudRegion) {
      this.d.toast.error("Missing project configuration for handoff");
      return null;
    }
    return {
      apiHost: getCloudUrlFromRegion(auth.cloudRegion),
      projectId: auth.currentProjectId,
    };
  }

  private async runHandoffPreflight(
    taskId: string,
    runId: string,
    repoPath: string,
    auth: { apiHost: string; projectId: number },
  ): Promise<Awaited<ReturnType<typeof this.d.trpc.handoff.preflight.query>>> {
    const preflight = await this.d.trpc.handoff.preflight.query({
      taskId,
      runId,
      repoPath,
      apiHost: auth.apiHost,
      teamId: auth.projectId,
    });
    if (!preflight.canHandoff) {
      this.d.store.updateSession(runId, {
        handoffInProgress: false,
      });
      throw new Error(preflight.reason ?? "Cannot hand off to local");
    }
    return preflight;
  }

  private async executeHandoff(
    taskId: string,
    runId: string,
    repoPath: string,
    auth: { apiHost: string; projectId: number },
    localGitState?: Awaited<
      ReturnType<typeof this.d.trpc.handoff.preflight.query>
    >["localGitState"],
  ): Promise<void> {
    const result = await this.d.trpc.handoff.execute.mutate({
      taskId,
      runId,
      repoPath,
      apiHost: auth.apiHost,
      teamId: auth.projectId,
      localGitState,
    });
    if (!result.success) {
      throw new Error(result.error ?? "Handoff failed");
    }
  }

  private transitionToLocalSession(runId: string): void {
    this.d.store.updateSession(runId, {
      isCloud: false,
      cloudStatus: undefined,
      cloudStage: undefined,
      cloudOutput: undefined,
      cloudErrorMessage: undefined,
      cloudBranch: undefined,
      status: "connected",
    });
  }

  async retryCloudTaskWatch(taskId: string): Promise<void> {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session?.isCloud) {
      throw new Error("No active cloud session for task");
    }

    const previousErrorTitle = session.errorTitle;
    const previousErrorMessage = session.errorMessage;
    const previousErrorRetryable = session.errorRetryable;

    this.d.store.updateSession(session.taskRunId, {
      status: "disconnected",
      errorTitle: undefined,
      errorMessage: undefined,
      errorRetryable: undefined,
      isPromptPending: false,
    });

    try {
      await this.d.trpc.cloudTask.retry.mutate({
        taskId,
        runId: session.taskRunId,
      });
    } catch (error) {
      this.d.store.updateSession(session.taskRunId, {
        status: "error",
        errorTitle: previousErrorTitle,
        errorMessage: previousErrorMessage,
        errorRetryable: previousErrorRetryable,
      });
      throw error;
    }

    // The main-process retry of an already-bootstrapped
    // watcher only reconnects SSE (`start=latest`) and emits no fresh
    // status/snapshot for an idle run, so the update-driven trigger in
    // `handleCloudTaskUpdate` would never fire, the queued message would
    // stay stuck. Attempt the same guarded recovery here once the reconnect
    // request has been accepted. No-ops unless a queue is stranded on an
    // idle, provably-alive run.
    this.tryRecoverIdleCloudQueue(session.taskRunId);
  }

  /**
   * Retries every cloud session whose stream is in the `error` state, i.e. the
   * main process exhausted its SSE reconnect budget and surfaced the manual
   * Retry button. Invoked on window focus so users coming back to the app
   * after a Django deploy, laptop sleep, or network blip don't have to click
   * Retry themselves.
   */
  public retryUnhealthyCloudSessions(): void {
    const sessions = this.d.store.getSessions();
    for (const session of Object.values(sessions)) {
      if (!session.isCloud) continue;
      if (session.status !== "error") continue;
      this.d.log.info("Auto-retrying errored cloud session on focus", {
        taskId: session.taskId,
      });
      this.retryCloudTaskWatch(session.taskId).catch((error) => {
        this.d.log.warn("Auto-retry of errored cloud session failed", {
          taskId: session.taskId,
          error,
        });
      });
    }
  }

  /**
   * Recovers cloud sessions after reconnect: retries errored streams and
   * flushes stranded queues (same steps as the window-focus and auth-restored
   * paths). Local sessions recover on their own via `reconcileLocalConnection`.
   */
  public recoverAfterReconnect(): void {
    this.retryUnhealthyCloudSessions();
    this.flushQueuedCloudMessagesAfterAuthRestored();
  }

  public flushQueuedCloudMessagesAfterAuthRestored(): void {
    const sessions = this.d.store.getSessions();
    for (const session of Object.values(sessions)) {
      if (!session.isCloud || session.messageQueue.length === 0) continue;
      this.scheduleCloudQueueFlush(session.taskId, "auth_restored");
    }
  }

  public countQueuedCloudMessages(): number {
    const sessions = this.d.store.getSessions();
    let count = 0;
    for (const session of Object.values(sessions)) {
      if (!session.isCloud) continue;
      count += session.messageQueue.length;
    }
    return count;
  }

  public updateSessionTaskTitle(taskId: string, taskTitle: string): void {
    const session = this.d.store.getSessionByTaskId(taskId);
    if (!session) return;

    if (session.taskTitle === taskTitle) return;

    this.d.store.updateSession(session.taskRunId, { taskTitle });
  }

  public startActivityHeartbeat(taskRunId: string): () => void {
    const record = () => {
      this.d.trpc.agent.recordActivity.mutate({ taskRunId }).catch(() => {});
    };

    record();
    const existing = this.activityHeartbeats.get(taskRunId);
    if (existing) {
      clearInterval(existing);
    }
    const heartbeat = setInterval(record, ACTIVITY_HEARTBEAT_INTERVAL_MS);
    this.activityHeartbeats.set(taskRunId, heartbeat);

    return () => {
      clearInterval(heartbeat);
      this.activityHeartbeats.delete(taskRunId);
    };
  }

  public reconcileTaskConnection(
    params: ReconcileTaskConnectionParams,
  ): () => void {
    const {
      task,
      session,
      repoPath,
      isCloud,
      isSuspended,
      isOnline,
      cloudAuth,
      onCloudStatusChange,
    } = params;

    if (isCloud) {
      // Local connects bound the session budget inside connectToTask; cloud
      // watches would otherwise never trigger eviction.
      this.sessionLastUsedAt.set(task.id, Date.now());
      void this.evictIdleSessions(task.id);
      return this.reconcileCloudConnection(
        task,
        cloudAuth,
        onCloudStatusChange,
      );
    }

    if (repoPath) {
      return this.reconcileLocalConnection({
        task,
        session,
        repoPath,
        isOnline,
        isSuspended,
      });
    }

    this.logReconcileSkipOnce(task.id, "no-workspace-path", {
      hasRun: !!task.latest_run?.id,
    });
    this.loadLogsOnlyIfDisconnected(task, session);
    return () => {};
  }

  private logReconcileSkipOnce(
    taskId: string,
    reason: string,
    context: Record<string, unknown> = {},
  ): void {
    const key = `${taskId}:${reason}`;
    if (this.reconcileSkipLogged.has(key)) return;
    this.reconcileSkipLogged.add(key);
    this.d.log.info("Skipping local session reconcile", {
      taskId,
      reason,
      ...context,
    });
  }

  public markTaskCreationInFlight(taskId: string): void {
    this.taskCreationMarks.set(taskId, Date.now());
  }

  private isTaskCreationInFlight(taskId: string): boolean {
    const markedAt = this.taskCreationMarks.get(taskId);
    if (markedAt === undefined) return false;
    const expired =
      Date.now() - markedAt > SessionService.TASK_CREATION_IN_FLIGHT_TTL_MS;
    if (expired) {
      this.taskCreationMarks.delete(taskId);
      return false;
    }
    return true;
  }

  private reconcileCloudConnection(
    task: Task,
    cloudAuth: CloudConnectionAuth,
    onCloudStatusChange?: () => void,
  ): () => void {
    this.updateSessionTaskTitle(
      task.id,
      task.title || task.description || "Cloud Task",
    );

    const runId = task.latest_run?.id;
    if (!runId) return () => {};
    if (cloudAuth.status !== "authenticated") return () => {};
    if (!cloudAuth.bootstrapComplete) return () => {};
    if (!cloudAuth.projectId || !cloudAuth.cloudRegion) return () => {};

    const initialMode =
      typeof task.latest_run?.state?.initial_permission_mode === "string"
        ? task.latest_run.state.initial_permission_mode
        : undefined;
    const adapter =
      task.latest_run?.runtime_adapter === "codex" ? "codex" : "claude";
    const initialModel = task.latest_run?.model ?? undefined;
    const initialReasoningEffort =
      task.latest_run?.reasoning_effort ?? undefined;

    return this.watchCloudTask(
      task.id,
      runId,
      getCloudUrlFromRegion(cloudAuth.cloudRegion),
      cloudAuth.projectId,
      onCloudStatusChange,
      task.latest_run?.log_url,
      initialMode,
      adapter,
      initialModel,
      task.description ?? undefined,
      undefined,
      task.latest_run?.status,
      initialReasoningEffort,
      task.latest_run?.state,
    );
  }

  private reconcileLocalConnection(params: {
    task: Task;
    session: ReconcileSessionState | undefined;
    repoPath: string;
    isOnline: boolean;
    isSuspended?: boolean;
  }): () => void {
    const { task, session, repoPath, isOnline, isSuspended } = params;
    const taskId = task.id;

    if (this.reconcilingTasks.has(taskId)) return () => {};
    if (!isOnline) return () => {};
    if (session?.isCloud) return () => {};
    if (isSuspended) return () => {};

    if (session?.status === "error" && session?.idleKilled) {
      const taskRunId = session.taskRunId;
      this.reconcilingTasks.add(taskId);
      this.clearSessionError(taskId, repoPath)
        .catch((error) => {
          this.d.log.error("Auto-reconnect after idle kill failed", { error });
          this.d.store.updateSession(taskRunId, {
            idleKilled: false,
            errorMessage:
              "Session disconnected due to inactivity. Click Retry to reconnect.",
          });
        })
        .finally(() => {
          this.reconcilingTasks.delete(taskId);
        });
      return () => {
        this.reconcilingTasks.delete(taskId);
      };
    }

    if (
      session?.status === "connected" ||
      session?.status === "connecting" ||
      session?.status === "error"
    ) {
      return () => {};
    }

    const connectParams: ConnectParams = { task, repoPath };

    // A local task with no run means creation was interrupted before its
    // first run started (e.g. the app quit for an update mid-setup). Connect
    // fresh and deliver the prompt persisted as the task description, unless
    // a creation saga is actively working on this task right now. Recovery
    // replays the description as literal text; original attachments are gone.
    if (!task.latest_run?.id) {
      if (this.isTaskCreationInFlight(taskId)) {
        this.logReconcileSkipOnce(taskId, "creation-in-flight");
        return () => {};
      }
      this.d.log.info("Recovering local task with no run", {
        taskId,
        hasDescription: !!task.description,
      });
      if (task.description) {
        connectParams.initialPrompt = [
          { type: "text", text: task.description },
        ];
      }
    }

    this.reconcilingTasks.add(taskId);
    this.connectToTask(connectParams).finally(() => {
      this.reconcilingTasks.delete(taskId);
    });

    return () => {
      this.reconcilingTasks.delete(taskId);
    };
  }

  private loadLogsOnlyIfDisconnected(
    task: Task,
    session: ReconcileSessionState | undefined,
  ): void {
    if (session && session.eventCount > 0) return;
    if (!task.latest_run?.id || !task.latest_run?.log_url) return;

    this.loadLogsOnly({
      taskId: task.id,
      taskRunId: task.latest_run.id,
      taskTitle: task.title || task.description || "Task",
      logUrl: task.latest_run.log_url,
    });
  }

  public resolveAllowAlwaysUpgradeMode(
    modeOption: SessionConfigOption | undefined,
  ): string | undefined {
    if (modeOption?.type !== "select") return undefined;
    const availableIds = new Set(
      flattenSelectOptions(modeOption.options).map((opt) => opt.value),
    );
    if (availableIds.has("acceptEdits")) return "acceptEdits";
    if (availableIds.has("auto")) return "auto";
    return undefined;
  }

  public applyAllowAlwaysUpgrade(
    taskId: string,
    modeOption: SessionConfigOption | undefined,
  ): void {
    const upgradeMode = this.resolveAllowAlwaysUpgradeMode(modeOption);
    if (!upgradeMode) return;
    this.setSessionConfigOptionByCategory(taskId, "mode", upgradeMode);
  }

  async resolvePermissionSelection(
    taskId: string,
    permission: PermissionRequest & { toolCallId: string },
    optionId: string,
    modeOption: SessionConfigOption | undefined,
    customInput?: string,
    answers?: Record<string, string>,
  ): Promise<PermissionSelectionPlan> {
    const plan = planPermissionResponse(permission, optionId, customInput);

    if (plan.applyAllowAlwaysUpgrade) {
      this.applyAllowAlwaysUpgrade(taskId, modeOption);
    }

    await this.respondToPermission(
      taskId,
      permission.toolCallId,
      optionId,
      plan.respondWithCustomInput ? customInput : undefined,
      answers,
    );

    return plan;
  }

  async cancelPermissionAndPrompt(
    taskId: string,
    toolCallId: string,
  ): Promise<void> {
    await this.cancelPermission(taskId, toolCallId);
    await this.cancelPrompt(taskId);
  }

  public selectLatestPlan(events: AcpMessage[]): SessionPlan | null {
    return selectLatestPlan(events);
  }

  public maybeRevertBypassMode(
    taskId: string | undefined,
    options: {
      isCloud: boolean;
      allowBypassPermissions: boolean;
      currentModeId: string | boolean | undefined;
      modeOption: SessionConfigOption | undefined;
    },
  ): void {
    if (options.allowBypassPermissions) return;
    if (options.isCloud) return;
    const isBypass =
      options.currentModeId === "bypassPermissions" ||
      options.currentModeId === "full-access";
    if (!isBypass || !taskId) return;
    const target = resolveBypassRevertMode(options.modeOption);
    if (!target) return;
    this.setSessionConfigOptionByCategory(taskId, "mode", target);
  }

  /**
   * Drain the cloud queue, the deferral breaks out of
   * the synchronous store-update frame so the dispatcher reads committed
   * state; `sendQueuedCloudMessages` is reentrancy-guarded so stacked
   * schedules from multiple triggers collapse to one.
   */
  private scheduleCloudQueueFlush(
    taskId: string,
    reason: string,
    options?: { force?: boolean },
  ): void {
    if (
      this.scheduledCloudQueueFlushes.has(taskId) ||
      this.dispatchingCloudQueues.has(taskId)
    ) {
      return;
    }

    this.scheduledCloudQueueFlushes.add(taskId);
    setTimeout(() => {
      this.scheduledCloudQueueFlushes.delete(taskId);
      this.sendQueuedCloudMessages(taskId, options).catch((err) =>
        this.d.log.error("cloud queue flush failed", {
          taskId,
          reason,
          error: err,
        }),
      );
    }, 0);
  }

  /**
   * Guarded recovery for a queued cloud message stranded by a transport
   * drop on an idle, already-bootstrapped run.
   *
   * `run_started` is normally the canonical "agent is ready" trigger and
   * would race with `sendInitialTaskMessage` while still booting, so the
   * safe default remains "drain only once status is connected". But an
   * idle run stays `in_progress` on the server while emitting NO fresh
   * `run_started`/`turn_complete` (those only fire on boot or a new turn).
   * If an SSE transport drop or the `retryCloudTaskWatch` it triggers
   * flipped the session to disconnected/error AFTER the agent already
   * booted for this exact run, nothing flips it back to "connected" and
   * the queued message is stranded forever. When the run is provably
   * alive (`cloudStatus === "in_progress"`) and the agent provably idle
   * for THIS run (`isAgentIdleForRun`), recover readiness and drain.
   */
  private tryRecoverIdleCloudQueue(
    taskRunId: string,
    options?: { serverSandboxAlive?: boolean | null },
  ): void {
    const session = this.d.store.getSessions()[taskRunId];
    if (!session?.isCloud || session.messageQueue.length === 0) {
      return;
    }
    if (session.cloudStatus !== "in_progress") {
      return;
    }
    if (
      this.scheduledCloudQueueFlushes.has(session.taskId) ||
      this.dispatchingCloudQueues.has(session.taskId)
    ) {
      return;
    }

    const recoverableAfterTransportDrop =
      (session.status === "disconnected" || session.status === "error") &&
      !session.isPromptPending;
    const serverReportsSandboxStopped =
      options?.serverSandboxAlive === false && recoverableAfterTransportDrop;

    if (session.status !== "connected" && !recoverableAfterTransportDrop) {
      return;
    }

    // A local prompt in flight means a queued follow-up would double-send.
    // The idle scan below is still the real safety check after reconnect.
    if (session.isPromptPending) {
      return;
    }

    if (serverReportsSandboxStopped) {
      this.d.log.info("Recovering cloud queue after sandbox stopped", {
        taskId: session.taskId,
        previousStatus: session.status,
      });
      this.scheduleCloudQueueFlush(session.taskId, "sandbox-stopped-recovery", {
        force: true,
      });
      return;
    }

    // The agent must be provably idle for this run, the
    // connected path included. `status: "connected"` alone is NOT proof of
    // idleness: the `_posthog/run_started` handler flips status to
    // "connected" before the initial/resume turn even starts, so a
    // connected-but-not-idle session is mid-boot. Draining now would race
    // with `sendInitialTaskMessage`/`sendResumeMessage` and one prompt
    // would be cancelled. Only `_posthog/turn_complete` makes the agent
    // idle for the run.
    const idleResult = this.cloudRunIdleTracker.evaluateIdle(session);
    if (!idleResult.idle) {
      return;
    }
    if (idleResult.shouldCacheToStore) {
      this.d.store.updateSession(taskRunId, {
        agentIdleForRunId: taskRunId,
      });
    }

    if (recoverableAfterTransportDrop) {
      this.d.store.updateSession(taskRunId, {
        status: "connected",
        errorTitle: undefined,
        errorMessage: undefined,
      });
      this.d.log.info(
        "Recovered cloud session readiness after transport drop",
        {
          taskId: session.taskId,
          previousStatus: session.status,
        },
      );
    }

    this.scheduleCloudQueueFlush(session.taskId, "idle-run-recovery");
  }

  private handleCloudTaskUpdate(
    taskRunId: string,
    update: CloudTaskUpdatePayload,
  ): void {
    if (update.kind === "error") {
      this.d.store.updateSession(taskRunId, {
        status: "error",
        errorTitle: update.errorTitle,
        errorMessage:
          update.errorMessage ??
          "Lost connection to the cloud run. Retry to reconnect.",
        errorRetryable: update.retryable,
        isPromptPending: false,
      });
      return;
    }

    if (update.kind === "permission_request") {
      this.handleCloudPermissionRequest(taskRunId, update);
      return;
    }

    // Append new log entries with dedup guard
    if (
      (update.kind === "logs" || update.kind === "snapshot") &&
      update.newEntries.length > 0
    ) {
      // Cloud streams deliver `session/update` notifications as regular log
      // entries rather than live ACP messages. Without this, config changes
      // made mid-run (e.g. plan-approval switching to bypassPermissions) never
      // reach the session store and the footer mode selector stays stale.
      const latestConfigOptions = extractLatestConfigOptionsFromEntries(
        update.newEntries,
      );
      if (latestConfigOptions) {
        this.d.store.updateSession(taskRunId, {
          configOptions: latestConfigOptions,
        });
        this.d.setPersistedConfigOptions(taskRunId, latestConfigOptions);
      }

      const session = this.d.store.getSessions()[taskRunId];
      const currentCount = session?.processedLineCount ?? 0;
      const expectedCount = update.totalEntryCount;
      const plan = classifyCloudLogAppend(
        currentCount,
        expectedCount,
        update.newEntries.length,
      );

      if (plan.kind === "caught-up") {
        // Already caught up — skip duplicate entries
      } else if (plan.kind === "append-tail") {
        const entriesToAppend = update.newEntries.slice(-plan.tailCount);
        const newEvents = convertStoredEntriesToEvents(
          entriesToAppend,
          undefined,
          {
            taskRunId,
            startEntryIndex: expectedCount - entriesToAppend.length,
          },
        );
        if (hasSessionPromptEvent(newEvents)) {
          this.d.store.clearTailOptimisticItems(taskRunId);
        }
        this.d.store.appendEvents(taskRunId, newEvents, expectedCount);
        this.updatePromptStateFromEvents(taskRunId, newEvents, {
          isLive: update.kind === "logs",
        });
      } else {
        this.cloudLogGapReconciler.reconcile({
          taskId: update.taskId,
          taskRunId,
          expectedCount,
          currentCount,
          newEntries: update.newEntries,
          logUrl: session?.logUrl,
        });
      }
    }

    // Evaluated once, before updateCloudStatus below can mutate cloudStatus.
    const isStaleNonTerminalStatus = this.isStaleNonTerminalCloudUpdate(
      taskRunId,
      update,
    );

    if (
      update.kind === "snapshot" &&
      !isTerminalStatus(update.status) &&
      !isStaleNonTerminalStatus
    ) {
      this.surfacePersistedPendingPermissions(taskRunId, update.newEntries);
    }

    // NOTE: Don't auto-flush on `!isPromptPending && queue.length > 0` here.
    // Setup-phase log batches (`_posthog/progress`, `_posthog/console`) stream
    // in BEFORE the agent emits its initial `session/prompt` request, so
    // `isPromptPending` is still false during those batches — firing the
    // dispatcher then races with the agent's initial `clientConnection.prompt`.
    // The canonical "agent is idle" signal is `_posthog/turn_complete`, which
    // is handled in `updatePromptStateFromEvents`.

    // Update cloud status fields if present
    if (update.kind === "status" || update.kind === "snapshot") {
      if (!isStaleNonTerminalStatus) {
        this.d.store.updateCloudStatus(taskRunId, {
          status: update.status,
          stage: update.stage,
          output: update.output,
          errorMessage: update.errorMessage,
          branch: update.branch,
        });

        if (update.status === "in_progress") {
          this.tryRecoverIdleCloudQueue(taskRunId, {
            serverSandboxAlive: update.sandboxAlive,
          });
        }
      }

      if (isTerminalStatus(update.status)) {
        // Pending resume messages can never be sent to a settled run.
        this.clearTerminalCloudPromptState(taskRunId);
        this.stopCloudTaskWatch(update.taskId);
      }
    }
  }

  async getCloudAttachmentPreviewUrl(
    taskId: string,
    runId: string,
    artifactId: string,
  ): Promise<string | null> {
    const authStatus = await this.getAuthCredentialsStatus();
    if (authStatus.kind !== "ready") return null;

    try {
      const artifacts = await this.getCloudAttachmentManifest(
        authStatus.auth.client,
        `${authStatus.auth.apiHost}:${authStatus.auth.projectId}`,
        taskId,
        runId,
      );
      const artifact = artifacts.find(
        (candidate) => candidate.id === artifactId,
      );
      if (!artifact?.storage_path) return null;

      return await authStatus.auth.client.presignTaskRunArtifact(
        taskId,
        runId,
        artifact.storage_path,
      );
    } catch (error) {
      this.d.log.warn("Failed to resolve cloud attachment preview", {
        taskId,
        runId,
        artifactId,
        error: String(error),
      });
      return null;
    }
  }

  async getCloudRunArtifacts(
    taskId: string,
    runId: string,
  ): Promise<TaskRunArtifact[]> {
    const authStatus = await this.getAuthCredentialsStatus();
    if (authStatus.kind !== "ready") return [];

    return this.getCloudAttachmentManifest(
      authStatus.auth.client,
      `${authStatus.auth.apiHost}:${authStatus.auth.projectId}`,
      taskId,
      runId,
    );
  }

  private getCloudAttachmentManifest(
    client: AuthClient,
    authIdentity: string,
    taskId: string,
    runId: string,
  ): Promise<TaskRunArtifact[]> {
    const key = `${authIdentity}:${taskId}:${runId}`;
    const existing = this.cloudAttachmentManifestRequests.get(key);
    if (existing) return existing;

    const request = client
      .getTaskRun(taskId, runId)
      .then((run: { artifacts?: TaskRunArtifact[] }) => run.artifacts ?? []);
    this.cloudAttachmentManifestRequests.set(key, request);

    const clear = () => {
      if (this.cloudAttachmentManifestRequests.get(key) === request) {
        this.cloudAttachmentManifestRequests.delete(key);
      }
    };
    void request.then(clear, clear);
    return request;
  }

  // --- Helper Methods ---

  private async resolveCloudPrompt(
    prompt: string | ContentBlock[],
  ): Promise<string | ContentBlock[]> {
    if (typeof prompt !== "string") {
      return prompt;
    }

    const resolver = this.d.h.resolveLocalSkillCommandPrompt;
    if (!resolver) {
      return prompt;
    }

    try {
      return (await resolver(prompt)) ?? prompt;
    } catch (error) {
      this.d.log.warn("Failed to resolve local skill command prompt", {
        error: String(error),
      });
      return prompt;
    }
  }

  private async getAuthCredentialsStatus(): Promise<AuthCredentialsStatus> {
    const authState = await this.d.fetchAuthState();
    // `bootstrapComplete === false` also covers the pre-initialize window where
    // status is still the default "anonymous" but auth has not resolved yet.
    if (
      authState.status === "restoring" ||
      authState.bootstrapComplete === false
    ) {
      return { kind: "restoring" };
    }

    const apiHost = authState.cloudRegion
      ? getCloudUrlFromRegion(authState.cloudRegion)
      : null;
    const projectId = authState.currentProjectId;
    const client = this.d.createAuthenticatedClient(authState);

    if (!apiHost || !projectId || !client) return { kind: "missing" };
    return { kind: "ready", auth: { apiHost, projectId, client } };
  }

  private queueRestoringCloudPrompt(
    session: AgentSession,
    prompt: string | ContentBlock[],
    reason: string,
  ): { stopReason: "queued" } {
    const transport = this.d.h.getCloudPromptTransport(prompt);
    this.d.store.enqueueMessage(session.taskId, transport.promptText, prompt);
    this.d.log.info(reason, {
      taskId: session.taskId,
      queueLength: session.messageQueue.length + 1,
    });
    return { stopReason: "queued" };
  }

  private parseLogContent(content: string): ParsedSessionLogs {
    return parseSessionLogContent(content, {
      onParseError: (line) =>
        this.d.log.warn("Failed to parse log entry", { line }),
    });
  }

  /**
   * Paint the tail of a task's local log immediately so a big transcript shows
   * its latest turns in tens of ms, instead of blocking on the full-log read +
   * IPC transfer. This is a throwaway fast-paint: the authoritative full read +
   * connect (`reconnectToLocalSession`) replaces this session shortly after with
   * correct processed-line tracking. No-op when a session already exists, the
   * host doesn't expose the tail read, or there's no local log.
   */
  private async paintTailFirst(
    taskRunId: string,
    taskId: string,
    taskTitle: string,
    logUrl: string,
  ): Promise<void> {
    const tailQuery = this.d.trpc.logs.readLocalLogsTail;
    if (!tailQuery) return;
    if (this.d.store.getSessionByTaskId(taskId)) return;
    try {
      const res = (await tailQuery.query({
        taskRunId,
        maxBytes: OPEN_TAIL_BYTES,
      })) as { content: string; truncated: boolean } | null;
      if (!res?.content?.trim()) return;
      // The full read may have set the session while we awaited the tail.
      if (this.d.store.getSessionByTaskId(taskId)) return;
      const { rawEntries } = this.parseLogContent(res.content);
      if (rawEntries.length === 0) return;
      const session = createBaseSession(taskRunId, taskId, taskTitle);
      session.events = convertStoredEntriesToEvents(rawEntries);
      session.logUrl = logUrl;
      session.status = "connecting";
      this.d.store.setSession(session);
    } catch (error) {
      this.d.log.debug("Tail-first paint skipped", { taskId, error });
    }
  }

  /**
   * Read the local log, preferring the collapsed read (superseded
   * tool_call_update snapshots merged server-side, so a tool-heavy log
   * doesn't cross the transport at full size). `originalLineCount` is the
   * pre-collapse line count when the collapsed read served the content.
   *
   * A tRPC proxy client fabricates a query object for any path, so a host
   * whose router lacks the procedure only fails at call time — fall back to
   * the plain read then, instead of misreporting the local log as unreadable.
   */
  private async readLocalLogsPreferCollapsed(
    taskRunId: string,
  ): Promise<{ content: string | null; originalLineCount?: number }> {
    const collapsedQuery = this.d.trpc.logs.readLocalLogsCollapsed;
    if (collapsedQuery) {
      try {
        const res = (await collapsedQuery.query({ taskRunId })) as {
          content: string;
          totalLineCount: number;
        } | null;
        return {
          content: res?.content ?? null,
          originalLineCount: res?.totalLineCount,
        };
      } catch {
        this.d.log.warn("Collapsed local log read failed, using plain read", {
          taskRunId,
        });
      }
    }
    const content = await this.d.trpc.logs.readLocalLogs.query({ taskRunId });
    return { content };
  }

  private async fetchSessionLogs(
    logUrl: string | undefined,
    taskRunId?: string,
    options: { minEntryCount?: number } = {},
  ): Promise<ParsedSessionLogs> {
    const empty: ParsedSessionLogs = {
      rawEntries: [],
      totalLineCount: 0,
      parseFailureCount: 0,
    };
    if (!logUrl && !taskRunId) return empty;
    let localResult: ParsedSessionLogs | undefined;

    if (taskRunId) {
      try {
        const { content, originalLineCount } =
          await this.readLocalLogsPreferCollapsed(taskRunId);
        if (content?.trim()) {
          const parsed = this.parseLogContent(content);
          // Collapsed content has fewer lines than the file, so keep the
          // server's original line count for resume/gap tracking.
          localResult =
            originalLineCount === undefined
              ? parsed
              : { ...parsed, totalLineCount: originalLineCount };
          if (
            !options.minEntryCount ||
            localResult.totalLineCount >= options.minEntryCount
          ) {
            return localResult;
          }
        }
      } catch {
        this.d.log.warn("Failed to read local logs, falling back to S3", {
          taskRunId,
        });
      }
    }

    if (!logUrl) return localResult ?? empty;

    try {
      const content = await this.d.trpc.logs.fetchS3Logs.query({ logUrl });
      if (!content?.trim()) return localResult ?? empty;

      const result = this.parseLogContent(content);

      if (taskRunId && result.rawEntries.length > 0) {
        this.d.trpc.logs.writeLocalLogs
          .mutate({ taskRunId, content })
          .catch((err: unknown) => {
            this.d.log.warn("Failed to cache S3 logs locally", {
              taskRunId,
              err,
            });
          });
      }

      if (
        localResult &&
        localResult.rawEntries.length > result.rawEntries.length
      ) {
        return localResult;
      }

      return result;
    } catch {
      return localResult ?? empty;
    }
  }

  private commitReconciledCloudEvents(
    taskRunId: string,
    rawEntries: StoredLogEntry[],
    logUrl: string | undefined,
    processedLineCount: number,
  ): void {
    const events = convertStoredEntriesToEvents(rawEntries, undefined, {
      taskRunId,
      startEntryIndex: 0,
    });
    if (hasSessionPromptEvent(events)) {
      this.d.store.clearTailOptimisticItems(taskRunId);
    }
    this.cloudRunIdleTracker.delete(taskRunId);
    this.d.store.updateSession(taskRunId, {
      events,
      isCloud: true,
      logUrl,
      processedLineCount,
    });
    this.updatePromptStateFromEvents(taskRunId, events);
  }

  private getSessionByRunId(taskRunId: string): AgentSession | undefined {
    const sessions = this.d.store.getSessions();
    return sessions[taskRunId];
  }

  private async appendAndPersist(
    taskId: string,
    session: AgentSession,
    event: AcpMessage,
    storedEntry: StoredLogEntry,
  ): Promise<void> {
    // Don't update processedLineCount - it tracks S3 log lines, not local events
    this.d.store.appendEvents(session.taskRunId, [event]);

    const client = await this.d.getAuthenticatedClient();
    if (client) {
      try {
        await client.appendTaskRunLog(taskId, session.taskRunId, [storedEntry]);
      } catch (error) {
        this.d.log.warn("Failed to persist event to logs", { error });
      }
    }
  }
}
