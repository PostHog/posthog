import { useEffect } from "react";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { usePreferencesStore } from "./stores/preferencesStore";

const log = logger.scope("server-auto-publish");

let saveGeneration = 0;
let saveQueue: Promise<void> = Promise.resolve();

export async function pullAutoPublishCloudRuns(
  projectId: number,
): Promise<void> {
  const generation = saveGeneration;
  const client = getPostHogApiClient();
  const { taskDefaults } = await client.getMyTaskRunConfig(projectId);
  if (generation !== saveGeneration) return;
  if (useAuthStore.getState().projectId !== projectId) return;
  const serverValue = taskDefaults.auto_publish_cloud_runs;
  if (serverValue === null) {
    await client.setMyTaskDefaults(projectId, {
      auto_publish_cloud_runs:
        usePreferencesStore.getState().autoPublishCloudRuns,
    });
    return;
  }
  usePreferencesStore.getState().setAutoPublishCloudRuns(serverValue);
}

export function saveAutoPublishCloudRuns(
  projectId: number,
  enabled: boolean,
): Promise<void> {
  saveGeneration += 1;
  const generation = saveGeneration;
  const { autoPublishCloudRuns: previous, setAutoPublishCloudRuns } =
    usePreferencesStore.getState();
  setAutoPublishCloudRuns(enabled);
  const save = saveQueue.then(() =>
    getPostHogApiClient().setMyTaskDefaults(projectId, {
      auto_publish_cloud_runs: enabled,
    }),
  );
  saveQueue = save.catch(() => undefined);
  return save.catch((error: unknown) => {
    if (generation === saveGeneration) {
      setAutoPublishCloudRuns(previous);
    }
    throw error;
  });
}

export function useServerAutoPublishSync(isConnected: boolean): void {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const projectId = useAuthStore((s) => s.projectId);

  useEffect(() => {
    if (!isAuthenticated || !projectId || !isConnected) return;
    pullAutoPublishCloudRuns(projectId).catch((error: unknown) => {
      log.warn("Failed to sync auto-publish setting", error);
    });
  }, [isAuthenticated, projectId, isConnected]);
}
