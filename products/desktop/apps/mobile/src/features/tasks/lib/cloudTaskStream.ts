import {
  type CloudTaskEngine,
  type CloudTaskFetch,
  createCloudTaskEngine,
} from "@posthog/core/cloud-task/cloud-task-engine";
import { CloudTaskEvent } from "@posthog/core/cloud-task/schemas";
import type { CloudTaskUpdatePayload } from "@posthog/shared";
import { fetch } from "expo/fetch";
import {
  authedFetch,
  type FetchInit,
  getBaseUrl,
  getProjectId,
} from "@/lib/api";
import { logger } from "@/lib/logger";

export interface WatchCloudTaskOptions {
  taskId: string;
  runId: string;
  onUpdate: (update: CloudTaskUpdatePayload) => void;
}

export interface WatchCloudTaskHandle {
  stop: () => void;
  reconnectIfDisconnected: () => void;
}

const mobileCloudTaskAnalytics = {
  initialize: () => {},
  track: () => {},
  identify: () => {},
  setCurrentUserId: () => {},
  getCurrentUserId: () => null,
  getOrCreateSessionId: () => "mobile-cloud-task",
  resetUser: () => {},
  captureException: () => {},
  flush: async () => {},
  shutdown: async () => {},
};

let cloudTaskEngine: CloudTaskEngine | null = null;

function getCloudTaskEngine(): CloudTaskEngine {
  if (cloudTaskEngine) {
    return cloudTaskEngine;
  }

  cloudTaskEngine = createCloudTaskEngine({
    auth: {
      authenticatedFetch: (url, init) =>
        authedFetch(url, init as FetchInit | undefined),
      getCloudContext: async () => ({
        apiHost: getBaseUrl(),
        teamId: getProjectId(),
      }),
    },
    analytics: mobileCloudTaskAnalytics,
    logger,
    streamFetch: fetch as CloudTaskFetch,
  });

  return cloudTaskEngine;
}

export function watchCloudTask({
  taskId,
  runId,
  onUpdate,
}: WatchCloudTaskOptions): WatchCloudTaskHandle {
  const engine = getCloudTaskEngine();
  const listener = (update: CloudTaskUpdatePayload): void => {
    if (update.taskId === taskId && update.runId === runId) {
      onUpdate(update);
    }
  };

  engine.on(CloudTaskEvent.Update, listener);
  engine.watch({
    taskId,
    runId,
    apiHost: getBaseUrl(),
    teamId: getProjectId(),
  });

  let stopped = false;

  return {
    stop: () => {
      if (stopped) {
        return;
      }
      stopped = true;
      engine.off(CloudTaskEvent.Update, listener);
      engine.unwatch(taskId, runId);
    },
    reconnectIfDisconnected: () => {
      if (!stopped) {
        engine.reconnectIfDisconnected(taskId, runId);
      }
    },
  };
}
