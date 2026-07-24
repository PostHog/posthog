import { fetch } from "expo/fetch";
import { createTimeoutSignal } from "@/lib/api";
import { logger } from "@/lib/logger";
import {
  fetchSessionLogs,
  getTaskRun,
  HttpError,
  streamCloudTask,
} from "../api";
import {
  type CloudTaskUpdatePayload,
  isKeepaliveEvent,
  isPermissionRequestEvent,
  isSseErrorEvent,
  isTaskRunStateEvent,
  isTerminalStatus,
  type StoredLogEntry,
  type TaskRun,
  type TaskRunStateEvent,
  type TaskRunStatus,
} from "../types";
import { parseSessionLogs } from "../utils/parseSessionLogs";
import { type SseEvent, SseEventParser } from "./sseParser";

const log = logger.scope("cloud-task-stream");

const MAX_SSE_RECONNECT_ATTEMPTS = 5;
const SSE_RECONNECT_BASE_DELAY_MS = 2_000;
const SSE_RECONNECT_MAX_DELAY_MS = 30_000;
const EVENT_BATCH_FLUSH_MS = 16;
const EVENT_BATCH_MAX_SIZE = 50;
const SESSION_LOG_PAGE_LIMIT = 5_000;

interface CloudTaskConnectionError {
  title: string;
  message: string;
  retryable: boolean;
  autoRetry?: boolean;
}

class CloudTaskStreamError extends Error {
  constructor(
    message: string,
    public readonly details: CloudTaskConnectionError,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "CloudTaskStreamError";
  }
}

function createStreamStatusError(status: number): CloudTaskStreamError {
  switch (status) {
    case 401:
      return new CloudTaskStreamError(
        "Cloud authentication expired",
        {
          title: "Cloud authentication expired",
          message: "Please reauthenticate and retry the cloud run stream.",
          retryable: true,
          autoRetry: false,
        },
        status,
      );
    case 403:
      return new CloudTaskStreamError(
        "Cloud access denied",
        {
          title: "Cloud access denied",
          message:
            "You no longer have access to this cloud run. Reauthenticate and retry.",
          retryable: true,
          autoRetry: false,
        },
        status,
      );
    case 404:
      return new CloudTaskStreamError(
        "Cloud run not found",
        {
          title: "Cloud run not found",
          message:
            "This cloud run could not be found. It may have been deleted or moved.",
          retryable: false,
          autoRetry: false,
        },
        status,
      );
    case 406:
      return new CloudTaskStreamError(
        "Cloud stream unavailable",
        {
          title: "Cloud stream unavailable",
          message:
            "The backend rejected the live stream request. Restart the backend and retry.",
          retryable: true,
          autoRetry: false,
        },
        status,
      );
    default:
      return new CloudTaskStreamError(
        `Stream request failed with status ${status}`,
        {
          title: "Cloud stream failed",
          message: `The cloud stream request failed with status ${status}. Retry to reconnect.`,
          retryable: true,
          autoRetry: true,
        },
        status,
      );
  }
}

function shouldFailWatcherForFetchStatus(status: number): boolean {
  return status === 401 || status === 403 || status === 404;
}

export interface WatchCloudTaskOptions {
  taskId: string;
  runId: string;
  onUpdate: (update: CloudTaskUpdatePayload) => void;
}

export interface WatchCloudTaskHandle {
  stop: () => void;
  reconnectIfDisconnected: () => void;
}

interface WatcherState {
  taskId: string;
  runId: string;
  onUpdate: (update: CloudTaskUpdatePayload) => void;
  stopped: boolean;
  sseAbortController: AbortController | null;
  reconnectTimeoutId: ReturnType<typeof setTimeout> | null;
  batchFlushTimeoutId: ReturnType<typeof setTimeout> | null;
  pendingLogEntries: StoredLogEntry[];
  totalEntryCount: number;
  reconnectAttempts: number;
  lastEventId: string | null;
  lastStatus: TaskRunStatus | null;
  lastStage: string | null;
  lastOutput: Record<string, unknown> | null;
  lastErrorMessage: string | null;
  lastBranch: string | null;
  lastStatusUpdatedAt: string | null;
  isBootstrapping: boolean;
  hasEmittedSnapshot: boolean;
  bufferedLogBatches: StoredLogEntry[][];
  failed: boolean;
  needsPostBootstrapReconnect: boolean;
  needsStopAfterBootstrap: boolean;
}

export function watchCloudTask(
  options: WatchCloudTaskOptions,
): WatchCloudTaskHandle {
  const watcher: WatcherState = {
    taskId: options.taskId,
    runId: options.runId,
    onUpdate: options.onUpdate,
    stopped: false,
    sseAbortController: null,
    reconnectTimeoutId: null,
    batchFlushTimeoutId: null,
    pendingLogEntries: [],
    totalEntryCount: 0,
    reconnectAttempts: 0,
    lastEventId: null,
    lastStatus: null,
    lastStage: null,
    lastOutput: null,
    lastErrorMessage: null,
    lastBranch: null,
    lastStatusUpdatedAt: null,
    isBootstrapping: false,
    hasEmittedSnapshot: false,
    bufferedLogBatches: [],
    failed: false,
    needsPostBootstrapReconnect: false,
    needsStopAfterBootstrap: false,
  };

  void bootstrapWatcher(watcher);

  return {
    stop: () => stopWatcher(watcher),
    reconnectIfDisconnected: () => {
      if (
        watcher.stopped ||
        watcher.failed ||
        isTerminalStatus(watcher.lastStatus)
      ) {
        return;
      }
      if (watcher.sseAbortController || watcher.reconnectTimeoutId) {
        return;
      }
      log.debug("Force reconnect after suspension", { runId: watcher.runId });
      watcher.reconnectAttempts = 0;
      void connectSse(watcher, {
        startLatest: !watcher.lastEventId,
      });
    },
  };
}

function stopWatcher(watcher: WatcherState): void {
  if (watcher.stopped) return;
  watcher.stopped = true;

  watcher.sseAbortController?.abort();
  watcher.sseAbortController = null;

  if (watcher.reconnectTimeoutId) {
    clearTimeout(watcher.reconnectTimeoutId);
    watcher.reconnectTimeoutId = null;
  }

  if (watcher.batchFlushTimeoutId) {
    clearTimeout(watcher.batchFlushTimeoutId);
    watcher.batchFlushTimeoutId = null;
  }

  // Drop any unflushed batches; the consumer is gone.
  watcher.pendingLogEntries = [];
  watcher.bufferedLogBatches = [];
}

async function bootstrapWatcher(watcher: WatcherState): Promise<void> {
  if (watcher.stopped) return;

  watcher.failed = false;
  watcher.needsPostBootstrapReconnect = false;
  watcher.needsStopAfterBootstrap = false;

  const run = await fetchTaskRunState(watcher);
  if (watcher.stopped || watcher.failed) return;

  if (!run) {
    failWatcher(watcher, {
      title: "Failed to load cloud run",
      message: "Could not fetch the cloud run state. Retry to reconnect.",
      retryable: true,
    });
    return;
  }

  applyTaskRunState(watcher, run);

  if (isTerminalStatus(run.status)) {
    const historicalEntries = await fetchHistoricalEntries(watcher, run);
    if (watcher.stopped || watcher.failed) return;
    if (!historicalEntries) {
      failWatcher(watcher, {
        title: "Failed to load task history",
        message:
          "Could not load the persisted cloud task logs. Retry to reconnect.",
        retryable: true,
      });
      return;
    }

    watcher.totalEntryCount = historicalEntries.length;
    watcher.hasEmittedSnapshot = true;
    emitSnapshot(watcher, historicalEntries);
    stopWatcher(watcher);
    return;
  }

  watcher.isBootstrapping = true;
  watcher.bufferedLogBatches = [];
  void connectSse(watcher, { startLatest: true });

  const historicalEntries = await fetchHistoricalEntries(watcher, run);
  if (watcher.stopped || watcher.failed) return;
  if (!historicalEntries) {
    failWatcher(watcher, {
      title: "Failed to load cloud run history",
      message:
        "Could not load the existing cloud run logs. Retry to reconnect.",
      retryable: true,
    });
    return;
  }

  // Flush any pending live entries into the bootstrap buffer before snapshot.
  flushLogBatch(watcher);

  watcher.totalEntryCount = historicalEntries.length;
  watcher.hasEmittedSnapshot = true;
  emitSnapshot(watcher, historicalEntries);

  watcher.isBootstrapping = false;
  drainBufferedLogBatches(watcher, historicalEntries);

  if (watcher.failed) return;

  if (watcher.needsStopAfterBootstrap || isTerminalStatus(watcher.lastStatus)) {
    watcher.needsStopAfterBootstrap = false;
    stopWatcher(watcher);
    return;
  }

  if (watcher.needsPostBootstrapReconnect) {
    watcher.needsPostBootstrapReconnect = false;
    scheduleReconnect(watcher, undefined, { countAttempt: false });
  }

  void verifyPostBootstrapStatus(watcher);
}

async function verifyPostBootstrapStatus(watcher: WatcherState): Promise<void> {
  if (watcher.stopped) return;
  if (isTerminalStatus(watcher.lastStatus)) return;

  const run = await fetchTaskRunState(watcher);
  if (watcher.stopped || !run) return;

  if (!applyTaskRunState(watcher, run)) return;
  if (isTerminalStatus(watcher.lastStatus)) return;

  emitStatus(watcher);
}

async function connectSse(
  watcher: WatcherState,
  options?: { startLatest?: boolean },
): Promise<void> {
  if (watcher.stopped) return;

  const controller = new AbortController();
  watcher.sseAbortController = controller;

  const parser = new SseEventParser();
  const decoder = new TextDecoder();

  try {
    const response = await streamCloudTask(watcher.taskId, watcher.runId, {
      lastEventId: watcher.lastEventId,
      startLatest: options?.startLatest,
      signal: controller.signal,
    });

    if (!response.ok) {
      throw createStreamStatusError(response.status);
    }

    if (!response.body) {
      throw new Error("Stream response did not include a body");
    }

    const reader = response.body.getReader();

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      if (!value) {
        continue;
      }

      const chunk = decoder.decode(value, { stream: true });
      const events = parser.parse(chunk);
      for (const event of events) {
        handleSseEvent(watcher, event);
        if (watcher.failed) return;
      }
    }

    const trailingEvents = parser.parse(decoder.decode());
    for (const event of trailingEvents) {
      handleSseEvent(watcher, event);
      if (watcher.failed) return;
    }

    flushLogBatch(watcher);

    if (controller.signal.aborted) {
      return;
    }

    await handleStreamCompletion(watcher, { reconnectIfNonTerminal: true });
  } catch (error) {
    flushLogBatch(watcher);

    if (controller.signal.aborted) {
      return;
    }

    if (
      error instanceof CloudTaskStreamError &&
      error.details.autoRetry === false
    ) {
      failWatcher(watcher, error.details);
      return;
    }

    const errorMessage =
      error instanceof Error ? error.message : "Unknown stream error";
    log.warn("Cloud task stream error", {
      runId: watcher.runId,
      error: errorMessage,
    });
    await handleStreamCompletion(watcher, {
      reconnectIfNonTerminal: true,
      reconnectError: error,
      countReconnectAttempt: true,
    });
  } finally {
    if (watcher.sseAbortController === controller) {
      watcher.sseAbortController = null;
    }
  }
}

function handleSseEvent(watcher: WatcherState, event: SseEvent): void {
  if (watcher.failed || watcher.stopped) return;

  if (event.id) {
    watcher.lastEventId = event.id;
  }

  if (event.event === "error") {
    const message = isSseErrorEvent(event.data)
      ? event.data.error
      : "Unknown stream error";
    throw new Error(message);
  }

  if (event.event === "keepalive" || isKeepaliveEvent(event.data)) {
    return;
  }

  watcher.reconnectAttempts = 0;

  if (isTaskRunStateEvent(event.data)) {
    if (applyTaskRunState(watcher, event.data)) {
      if (!watcher.isBootstrapping && !isTerminalStatus(watcher.lastStatus)) {
        emitStatus(watcher);
      }
    }
    return;
  }

  if (isPermissionRequestEvent(event.data)) {
    watcher.onUpdate({
      taskId: watcher.taskId,
      runId: watcher.runId,
      kind: "permission_request",
      requestId: event.data.requestId,
      toolCall: event.data.toolCall,
      options: event.data.options,
    });
    return;
  }

  // StoredLogEntry always has a string `type`. Anything else is a server
  // event the mobile client doesn't understand yet — drop it instead of
  // forwarding a malformed entry to convertStoredEntriesToEvents.
  if (
    typeof event.data !== "object" ||
    event.data === null ||
    typeof (event.data as { type?: unknown }).type !== "string"
  ) {
    log.warn("Skipping unrecognized SSE event", {
      runId: watcher.runId,
      eventName: event.event,
    });
    return;
  }

  watcher.pendingLogEntries.push(event.data as StoredLogEntry);
  if (watcher.pendingLogEntries.length >= EVENT_BATCH_MAX_SIZE) {
    flushLogBatch(watcher);
    return;
  }

  if (!watcher.batchFlushTimeoutId) {
    watcher.batchFlushTimeoutId = setTimeout(() => {
      watcher.batchFlushTimeoutId = null;
      flushLogBatch(watcher);
    }, EVENT_BATCH_FLUSH_MS);
  }
}

function flushLogBatch(watcher: WatcherState): void {
  if (watcher.pendingLogEntries.length === 0) return;

  if (watcher.batchFlushTimeoutId) {
    clearTimeout(watcher.batchFlushTimeoutId);
    watcher.batchFlushTimeoutId = null;
  }

  const entries = watcher.pendingLogEntries;
  watcher.pendingLogEntries = [];

  if (watcher.isBootstrapping) {
    watcher.bufferedLogBatches.push(entries);
    return;
  }

  watcher.totalEntryCount += entries.length;
  watcher.onUpdate({
    taskId: watcher.taskId,
    runId: watcher.runId,
    kind: "logs",
    newEntries: entries,
    totalEntryCount: watcher.totalEntryCount,
  });
}

function drainBufferedLogBatches(
  watcher: WatcherState,
  historicalEntries: StoredLogEntry[],
): void {
  if (watcher.bufferedLogBatches.length === 0) return;

  // Content-based dedup because SSE IDs (Redis stream IDs) don't exist in
  // the S3-backed historical entries — the JSON payload is the only shared key.
  const historicalCounts = new Map<string, number>();
  for (const entry of historicalEntries) {
    const serialized = JSON.stringify(entry);
    historicalCounts.set(
      serialized,
      (historicalCounts.get(serialized) ?? 0) + 1,
    );
  }

  for (const entries of watcher.bufferedLogBatches) {
    const dedupedEntries = entries.filter((entry) => {
      const serialized = JSON.stringify(entry);
      const remaining = historicalCounts.get(serialized) ?? 0;
      if (remaining <= 0) return true;
      historicalCounts.set(serialized, remaining - 1);
      return false;
    });

    if (dedupedEntries.length === 0) continue;

    watcher.totalEntryCount += dedupedEntries.length;
    watcher.onUpdate({
      taskId: watcher.taskId,
      runId: watcher.runId,
      kind: "logs",
      newEntries: dedupedEntries,
      totalEntryCount: watcher.totalEntryCount,
    });
  }

  watcher.bufferedLogBatches = [];
}

function emitSnapshot(watcher: WatcherState, entries: StoredLogEntry[]): void {
  watcher.onUpdate({
    taskId: watcher.taskId,
    runId: watcher.runId,
    kind: "snapshot",
    newEntries: entries,
    totalEntryCount: watcher.totalEntryCount,
    status: watcher.lastStatus ?? undefined,
    stage: watcher.lastStage,
    output: watcher.lastOutput,
    errorMessage: watcher.lastErrorMessage,
    branch: watcher.lastBranch,
  });
}

function emitStatus(watcher: WatcherState): void {
  watcher.onUpdate({
    taskId: watcher.taskId,
    runId: watcher.runId,
    kind: "status",
    status: watcher.lastStatus ?? undefined,
    stage: watcher.lastStage,
    output: watcher.lastOutput,
    errorMessage: watcher.lastErrorMessage,
    branch: watcher.lastBranch,
  });
}

function failWatcher(
  watcher: WatcherState,
  error: CloudTaskConnectionError,
): void {
  if (watcher.stopped) return;

  watcher.failed = true;
  watcher.isBootstrapping = false;
  watcher.pendingLogEntries = [];
  watcher.bufferedLogBatches = [];

  if (watcher.reconnectTimeoutId) {
    clearTimeout(watcher.reconnectTimeoutId);
    watcher.reconnectTimeoutId = null;
  }

  if (watcher.batchFlushTimeoutId) {
    clearTimeout(watcher.batchFlushTimeoutId);
    watcher.batchFlushTimeoutId = null;
  }

  watcher.sseAbortController?.abort();
  watcher.sseAbortController = null;

  watcher.onUpdate({
    taskId: watcher.taskId,
    runId: watcher.runId,
    kind: "error",
    errorTitle: error.title,
    errorMessage: error.message,
    retryable: error.retryable,
  });
}

function scheduleReconnect(
  watcher: WatcherState,
  error?: unknown,
  options: { countAttempt?: boolean } = {},
): void {
  if (
    watcher.stopped ||
    watcher.failed ||
    isTerminalStatus(watcher.lastStatus)
  ) {
    return;
  }

  if (watcher.reconnectTimeoutId) {
    clearTimeout(watcher.reconnectTimeoutId);
  }

  const countAttempt = options.countAttempt ?? true;
  if (countAttempt) {
    watcher.reconnectAttempts += 1;
  } else {
    watcher.reconnectAttempts = 0;
  }

  if (watcher.reconnectAttempts > MAX_SSE_RECONNECT_ATTEMPTS) {
    const details =
      error instanceof CloudTaskStreamError
        ? error.details
        : {
            title: "Cloud stream disconnected",
            message:
              "Lost connection to the cloud run stream. Retry to reconnect.",
            retryable: true,
          };
    failWatcher(watcher, details);
    return;
  }

  const delay = Math.min(
    SSE_RECONNECT_BASE_DELAY_MS *
      2 ** Math.max(watcher.reconnectAttempts - 1, 0),
    SSE_RECONNECT_MAX_DELAY_MS,
  );

  watcher.reconnectTimeoutId = setTimeout(() => {
    if (watcher.stopped) return;
    watcher.reconnectTimeoutId = null;
    void connectSse(watcher, {
      startLatest: watcher.isBootstrapping || watcher.hasEmittedSnapshot,
    });
  }, delay);
}

async function handleStreamCompletion(
  watcher: WatcherState,
  options: {
    reconnectIfNonTerminal: boolean;
    reconnectError?: unknown;
    countReconnectAttempt?: boolean;
  },
): Promise<void> {
  if (watcher.stopped) return;

  const { reconnectIfNonTerminal } = options;
  const run = await fetchTaskRunState(watcher);
  if (watcher.stopped || watcher.failed) return;

  if (watcher.isBootstrapping) {
    if (!run) {
      watcher.needsPostBootstrapReconnect = true;
      return;
    }

    applyTaskRunState(watcher, run);
    if (isTerminalStatus(watcher.lastStatus) || !reconnectIfNonTerminal) {
      watcher.needsStopAfterBootstrap = true;
    } else {
      watcher.needsPostBootstrapReconnect = true;
    }
    return;
  }

  if (!run) {
    scheduleReconnect(
      watcher,
      new CloudTaskStreamError("Failed to fetch terminal cloud run state", {
        title: "Cloud run state unavailable",
        message:
          "Could not fetch the latest cloud run state after the stream ended. Retry to reconnect.",
        retryable: true,
      }),
    );
    return;
  }

  const stateChanged = applyTaskRunState(watcher, run);

  if (!isTerminalStatus(watcher.lastStatus) && reconnectIfNonTerminal) {
    if (stateChanged) {
      emitStatus(watcher);
    }
    log.warn("Cloud task stream ended before terminal status", {
      runId: watcher.runId,
      status: watcher.lastStatus,
    });
    scheduleReconnect(watcher, options.reconnectError, {
      countAttempt: options.countReconnectAttempt ?? false,
    });
    return;
  }

  emitStatus(watcher);
  stopWatcher(watcher);
}

function applyTaskRunState(
  watcher: WatcherState,
  run:
    | Pick<
        TaskRun,
        | "status"
        | "stage"
        | "output"
        | "error_message"
        | "branch"
        | "updated_at"
      >
    | TaskRunStateEvent,
): boolean {
  const updatedAt = run.updated_at ?? null;
  if (
    updatedAt &&
    watcher.lastStatusUpdatedAt &&
    Date.parse(updatedAt) <= Date.parse(watcher.lastStatusUpdatedAt)
  ) {
    return false;
  }

  const nextStatus = run.status ?? watcher.lastStatus;
  const nextStage = run.stage ?? null;
  const nextOutput = run.output ?? null;
  const nextErrorMessage = run.error_message ?? null;
  const nextBranch = run.branch ?? null;

  const changed =
    nextStatus !== watcher.lastStatus ||
    nextStage !== watcher.lastStage ||
    JSON.stringify(nextOutput) !== JSON.stringify(watcher.lastOutput) ||
    nextErrorMessage !== watcher.lastErrorMessage ||
    nextBranch !== watcher.lastBranch;

  watcher.lastStatus = nextStatus ?? null;
  watcher.lastStage = nextStage;
  watcher.lastOutput = nextOutput;
  watcher.lastErrorMessage = nextErrorMessage;
  watcher.lastBranch = nextBranch;
  if (updatedAt) {
    watcher.lastStatusUpdatedAt = updatedAt;
  }

  return changed;
}

async function fetchTaskRunState(
  watcher: WatcherState,
): Promise<TaskRun | null> {
  try {
    return await getTaskRun(watcher.taskId, watcher.runId);
  } catch (error) {
    if (error instanceof HttpError) {
      log.warn("Cloud task status fetch failed", {
        runId: watcher.runId,
        status: error.status,
      });
      if (shouldFailWatcherForFetchStatus(error.status)) {
        failWatcher(watcher, createStreamStatusError(error.status).details);
      }
      return null;
    }
    log.warn("Cloud task status fetch error", {
      runId: watcher.runId,
      error,
    });
    return null;
  }
}

/**
 * Loads the historical log entries for the run, mirroring the desktop's
 * dual-source strategy:
 *  1. Try the paginated `session_logs/` API — the live source while a run
 *     is active. For older / archived runs this can come back empty even
 *     though the canonical log exists on S3.
 *  2. Fall back to the run's presigned `log_url` (S3 NDJSON), which is the
 *     canonical archive for completed runs.
 *
 * Returns `null` only when both sources fail outright (so the bootstrap can
 * surface a retryable error). An empty paginated result is treated as "no
 * data yet" and falls through to S3 — if S3 also has nothing we return the
 * empty array so the snapshot can still flip the session to `"connected"`.
 */
async function fetchHistoricalEntries(
  watcher: WatcherState,
  run: TaskRun,
): Promise<StoredLogEntry[] | null> {
  const paginated = await fetchAllSessionLogs(watcher);
  if (watcher.stopped || watcher.failed) return null;
  if (paginated && paginated.length > 0) return paginated;

  if (run.log_url) {
    const s3Entries = await fetchS3LogEntries(watcher, run.log_url);
    if (watcher.stopped || watcher.failed) return null;
    if (s3Entries && s3Entries.length > 0) return s3Entries;
  }

  // Both sources returned no rows. Prefer the paginated result (which is
  // `[]` rather than `null`) so the caller can still emit an empty snapshot
  // and the session flips to `"connected"` instead of hanging on loading.
  return paginated ?? null;
}

async function fetchS3LogEntries(
  watcher: WatcherState,
  logUrl: string,
): Promise<StoredLogEntry[] | null> {
  try {
    const response = await fetch(logUrl, {
      signal: createTimeoutSignal(15_000),
    });
    if (response.status === 404) {
      // No archived log yet for this run — not an error, just no data.
      return [];
    }
    if (!response.ok) {
      log.warn("S3 session log fetch returned non-OK", {
        runId: watcher.runId,
        status: response.status,
      });
      return null;
    }
    const content = await response.text();
    if (!content.trim()) return [];
    return parseSessionLogs(content).rawEntries;
  } catch (error) {
    log.warn("S3 session log fetch failed", {
      runId: watcher.runId,
      error,
    });
    return null;
  }
}

async function fetchAllSessionLogs(
  watcher: WatcherState,
): Promise<StoredLogEntry[] | null> {
  const entries: StoredLogEntry[] = [];
  let offset = 0;

  while (true) {
    if (watcher.stopped || watcher.failed) return null;
    try {
      const page = await fetchSessionLogs(watcher.taskId, watcher.runId, {
        limit: SESSION_LOG_PAGE_LIMIT,
        offset,
      });

      for (const entry of page.entries) {
        entries.push(entry);
      }
      if (!page.hasMore || page.entries.length === 0) {
        return entries;
      }
      offset += page.entries.length;
    } catch (error) {
      if (error instanceof HttpError) {
        log.warn("Cloud task session logs fetch failed", {
          runId: watcher.runId,
          status: error.status,
          offset,
        });
        if (shouldFailWatcherForFetchStatus(error.status)) {
          failWatcher(watcher, createStreamStatusError(error.status).details);
        }
        return null;
      }
      log.warn("Cloud task session logs fetch error", {
        runId: watcher.runId,
        offset,
        error,
      });
      return null;
    }
  }
}
