import { useEffect } from "react";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { usePreferencesStore } from "./stores/preferencesStore";

const log = logger.scope("server-auto-publish");

export async function pullAutoPublishCloudRuns(
  projectId: number,
): Promise<void> {
  const client = getPostHogApiClient();
  const { taskDefaults } = await client.getMyTaskRunConfig(projectId);
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

export async function saveAutoPublishCloudRuns(
  projectId: number,
  enabled: boolean,
): Promise<void> {
  const { autoPublishCloudRuns: previous, setAutoPublishCloudRuns } =
    usePreferencesStore.getState();
  setAutoPublishCloudRuns(enabled);
  try {
    await getPostHogApiClient().setMyTaskDefaults(projectId, {
      auto_publish_cloud_runs: enabled,
    });
  } catch (error) {
    setAutoPublishCloudRuns(previous);
    throw error;
  }
}

export function useServerAutoPublishSync(): void {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const projectId = useAuthStore((s) => s.projectId);

  useEffect(() => {
    if (!isAuthenticated || !projectId) return;
    pullAutoPublishCloudRuns(projectId).catch((error: unknown) => {
      log.warn("Failed to sync auto-publish setting", error);
    });
  }, [isAuthenticated, projectId]);
}
