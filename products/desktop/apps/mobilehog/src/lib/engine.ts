import {
  type CloudTaskEngine,
  type CloudTaskFetch,
  createCloudTaskEngine,
} from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type { CloudTaskUpdatePayload } from "@posthog/shared";
import { fetch } from "expo/fetch";
import { engineAnalytics } from "@/lib/analytics";
import {
  authedFetch,
  type FetchInit,
  getBaseUrl,
  getProjectId,
} from "@/lib/api";
import { sessionIdentity } from "@/lib/auth";
import { logger } from "@/lib/logger";

let engine: CloudTaskEngine | null = null;

function getEngine(): CloudTaskEngine {
  if (engine) return engine;
  const identity = sessionIdentity();
  const assertCurrent = (): void => {
    if (sessionIdentity() !== identity)
      throw new Error("Session changed. Sign in again.");
  };
  engine = createCloudTaskEngine({
    auth: {
      authenticatedFetch: (url, init) => {
        assertCurrent();
        return authedFetch(url, init as FetchInit | undefined);
      },
      getCloudContext: async () => {
        assertCurrent();
        return { apiHost: getBaseUrl(), teamId: getProjectId() };
      },
    },
    transcriptTailWindow: 200,
    analytics: engineAnalytics,
    logger,
    // React Native's global fetch cannot stream a body; expo/fetch can.
    streamFetch: ((url, init) =>
      fetch(url, { ...init, credentials: "omit" })) as CloudTaskFetch,
  });
  return engine;
}

export function resetEngine(): void {
  engine?.unwatchAll();
  engine = null;
}

export interface WatchHandle {
  stop: () => void;
  reconnectIfDisconnected: () => void;
}

export function watchRun(
  taskId: string,
  runId: string,
  onUpdate: (update: CloudTaskUpdatePayload) => void,
): WatchHandle {
  const instance = getEngine();
  const listener = (update: CloudTaskUpdatePayload): void => {
    if (update.taskId === taskId && update.runId === runId) {
      onUpdate(update);
    }
  };
  instance.on(CloudTaskEvent.Update, listener);
  // A watcher for this run may survive a reload; drop it so we get a snapshot.
  instance.unwatch(taskId, runId);
  instance.watch({
    taskId,
    runId,
    apiHost: getBaseUrl(),
    teamId: getProjectId(),
  });

  let stopped = false;
  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      instance.off(CloudTaskEvent.Update, listener);
      instance.unwatch(taskId, runId);
    },
    reconnectIfDisconnected: () => {
      if (!stopped) instance.reconnectIfDisconnected(taskId, runId);
    },
  };
}
