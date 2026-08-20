import type { StoredLogEntry } from "@posthog/shared";
import {
  type CloudLogGapDeficiency,
  type CloudLogGapReconcileRequest,
  classifyCloudLogGap,
  mergeCloudLogGapRequests,
} from "./cloudLogGap";

export interface CloudLogGapFetchResult {
  rawEntries: StoredLogEntry[];
  totalLineCount: number;
  parseFailureCount: number;
}

export interface CloudLogGapReconcilerSession {
  taskId: string;
  processedLineCount: number;
  logUrl: string | undefined;
}

export interface CloudLogGapReconcilerLogger {
  warn(message: string, data?: Record<string, unknown>): void;
}

/**
 * Host I/O the reconciler orchestrates over. The session service supplies these
 * (log fetching, store read, the commit-to-store side effect); the reconciler
 * owns the queue/coalesce/retry control flow and the gap-classification flow.
 */
export interface CloudLogGapReconcilerDeps {
  fetchLogs(
    logUrl: string | undefined,
    taskRunId: string,
    minEntryCount: number,
  ): Promise<CloudLogGapFetchResult>;
  getSession(taskRunId: string): CloudLogGapReconcilerSession | undefined;
  commit(
    taskRunId: string,
    rawEntries: StoredLogEntry[],
    logUrl: string | undefined,
    processedLineCount: number,
  ): void;
  logger: CloudLogGapReconcilerLogger;
}

interface ReconcileState {
  pendingRequest?: CloudLogGapReconcileRequest;
}

/**
 * Reconciles cloud session log gaps. When a streamed cloud update claims more
 * entries than it carried (a gap), the service hands the request here; the
 * reconciler fetches the authoritative log, decides via `classifyCloudLogGap`
 * whether to fill / commit-best-effort / wait, and coalesces concurrent
 * requests for the same run so only one fetch loop runs at a time.
 */
export class CloudLogGapReconciler {
  private readonly inFlight = new Map<string, ReconcileState>();
  private readonly deficiency = new Map<string, CloudLogGapDeficiency>();

  constructor(private readonly deps: CloudLogGapReconcilerDeps) {}

  /** Queue a reconcile. Concurrent requests for the same run are coalesced. */
  reconcile(request: CloudLogGapReconcileRequest): void {
    const reconcileKey = `${request.taskId}:${request.taskRunId}`;
    const existing = this.inFlight.get(reconcileKey);
    if (existing) {
      existing.pendingRequest = mergeCloudLogGapRequests(
        existing.pendingRequest,
        request,
      );
      return;
    }

    this.inFlight.set(reconcileKey, {});
    void this.runLoop(reconcileKey, request)
      .catch((err: unknown) => {
        this.deps.logger.warn("Failed to reconcile cloud task log gap", {
          taskId: request.taskId,
          taskRunId: request.taskRunId,
          err,
        });
      })
      .finally(() => {
        this.inFlight.delete(reconcileKey);
      });
  }

  /** Forget the tracked deficit for a run (on teardown / watch stop). */
  forgetDeficiency(taskRunId: string): void {
    this.deficiency.delete(taskRunId);
  }

  /** Drop all in-flight reconciles and tracked deficits (on full reset). */
  clear(): void {
    this.inFlight.clear();
    this.deficiency.clear();
  }

  private async runLoop(
    reconcileKey: string,
    initialRequest: CloudLogGapReconcileRequest,
  ): Promise<void> {
    let request: CloudLogGapReconcileRequest | undefined = initialRequest;

    while (request) {
      await this.reconcileOnce(request);
      const state = this.inFlight.get(reconcileKey);
      request = state?.pendingRequest;
      if (state) {
        state.pendingRequest = undefined;
      }
    }
  }

  private async reconcileOnce(
    request: CloudLogGapReconcileRequest,
  ): Promise<void> {
    const {
      taskId,
      taskRunId,
      expectedCount,
      currentCount,
      newEntries,
      logUrl,
    } = request;

    const { rawEntries, totalLineCount, parseFailureCount } =
      await this.deps.fetchLogs(logUrl, taskRunId, expectedCount);

    const session = this.deps.getSession(taskRunId);
    if (!session || session.taskId !== taskId) {
      return;
    }

    const action = classifyCloudLogGap({
      expectedCount,
      latestCount: session.processedLineCount ?? 0,
      totalLineCount,
      parseFailureCount,
      previousDeficiency: this.deficiency.get(taskRunId),
    });

    if (action.kind === "already-current") {
      this.deficiency.delete(taskRunId);
      return;
    }

    if (action.kind === "commit-best-effort") {
      this.deps.logger.warn(
        "Cloud task log gap unrecoverable; committing best-effort",
        {
          taskRunId,
          expectedCount,
          observedLineCount: totalLineCount,
          parseFailureCount,
          fetchedEntries: rawEntries.length,
          reason: action.reason,
        },
      );
    }

    if (action.kind === "fill" || action.kind === "commit-best-effort") {
      this.deficiency.delete(taskRunId);
      this.deps.commit(
        taskRunId,
        rawEntries,
        logUrl ?? session.logUrl,
        action.processedLineCount,
      );
      return;
    }

    this.deficiency.set(taskRunId, action.deficiency);
    this.deps.logger.warn("Cloud task log count inconsistency", {
      taskRunId,
      currentCount,
      expectedCount,
      fetchedCount: rawEntries.length,
      parseFailureCount,
      entriesReceived: newEntries.length,
    });
  }
}
