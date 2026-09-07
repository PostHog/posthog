import { type AgentSession, isJsonRpcRequest } from "@posthog/shared";
import { isNotification, POSTHOG_NOTIFICATIONS } from "./acpNotifications";

interface CloudRunIdleScanState {
  nextEventIndex: number;
  seenCurrentRunStart: boolean;
  idle: boolean;
}

export interface CloudRunIdleEvidenceSnapshot {
  taskRunId: string;
  eventCount: number;
  agentIdleForRunId: string | undefined;
  scanState?: CloudRunIdleScanState;
}

export interface CloudRunIdleRestoreResult {
  agentIdleForRunId: string | undefined;
}

export interface CloudRunIdleScanResult {
  idle: boolean;
  /** True when the scan path proved idle and the store can cache it. */
  shouldCacheToStore: boolean;
}

/**
 * Tracks idleness for cloud runs incrementally so repeated `in_progress`
 * updates don't re-scan the full event list each time.
 */
export class CloudRunIdleTracker {
  private scanStates = new Map<string, CloudRunIdleScanState>();

  clear(): void {
    this.scanStates.clear();
  }

  delete(taskRunId: string): void {
    this.scanStates.delete(taskRunId);
  }

  /**
   * Marks the run as busy. Sets `seenCurrentRunStart: true` even if a
   * `RUN_STARTED` notification was never observed because a prompt is
   * proof the run started.
   */
  markBusy(session: AgentSession): void {
    this.scanStates.set(session.taskRunId, {
      nextEventIndex: session.events.length,
      seenCurrentRunStart: true,
      idle: false,
    });
  }

  markIdle(session: AgentSession): void {
    this.scanStates.set(session.taskRunId, {
      nextEventIndex: session.events.length,
      seenCurrentRunStart: true,
      idle: true,
    });
  }

  capture(session: AgentSession): CloudRunIdleEvidenceSnapshot {
    const scanState = this.scanStates.get(session.taskRunId);
    return {
      taskRunId: session.taskRunId,
      eventCount: session.events.length,
      agentIdleForRunId: session.agentIdleForRunId,
      scanState: scanState ? { ...scanState } : undefined,
    };
  }

  restoreAfterFailedSend(
    snapshot: CloudRunIdleEvidenceSnapshot,
    session: AgentSession,
  ): CloudRunIdleRestoreResult | undefined {
    for (let i = snapshot.eventCount; i < session.events.length; i += 1) {
      const acpMsg = session.events[i];
      if (
        acpMsg &&
        isJsonRpcRequest(acpMsg.message) &&
        acpMsg.message.method === "session/prompt"
      ) {
        return undefined;
      }
    }

    const currentScanState = this.scanStates.get(snapshot.taskRunId);
    const stillAtFailedSendMarker =
      currentScanState?.nextEventIndex === snapshot.eventCount &&
      currentScanState.seenCurrentRunStart &&
      !currentScanState.idle;
    if (!stillAtFailedSendMarker) {
      return undefined;
    }

    if (snapshot.scanState) {
      this.scanStates.set(snapshot.taskRunId, { ...snapshot.scanState });
    } else {
      this.scanStates.delete(snapshot.taskRunId);
    }

    return { agentIdleForRunId: snapshot.agentIdleForRunId };
  }

  /**
   * Returns idleness for this run, scanning only events added since the
   * previous call. `shouldCacheToStore` is true when the scan path proved
   * idle instead of the `agentIdleForRunId` fast path.
   */
  evaluateIdle(session: AgentSession): CloudRunIdleScanResult {
    if (session.agentIdleForRunId === session.taskRunId) {
      return { idle: true, shouldCacheToStore: false };
    }

    let scanState = this.scanStates.get(session.taskRunId);
    if (!scanState || scanState.nextEventIndex > session.events.length) {
      scanState = {
        nextEventIndex: 0,
        seenCurrentRunStart: false,
        idle: false,
      };
    }

    for (let i = scanState.nextEventIndex; i < session.events.length; i += 1) {
      const acpMsg = session.events[i];
      if (!acpMsg) continue;
      const msg = acpMsg.message;
      if (
        "method" in msg &&
        isNotification(msg.method, POSTHOG_NOTIFICATIONS.RUN_STARTED)
      ) {
        const params = (msg as { params?: { runId?: unknown } }).params;
        if (params?.runId === session.taskRunId) {
          scanState.seenCurrentRunStart = true;
          scanState.idle = false;
        }
        continue;
      }
      if (!scanState.seenCurrentRunStart) {
        continue;
      }
      if (isJsonRpcRequest(msg) && msg.method === "session/prompt") {
        scanState.idle = false;
        continue;
      }
      if (
        "method" in msg &&
        isNotification(msg.method, POSTHOG_NOTIFICATIONS.TURN_COMPLETE)
      ) {
        scanState.idle = true;
      }
    }

    scanState.nextEventIndex = session.events.length;
    this.scanStates.set(session.taskRunId, scanState);

    return { idle: scanState.idle, shouldCacheToStore: scanState.idle };
  }
}
