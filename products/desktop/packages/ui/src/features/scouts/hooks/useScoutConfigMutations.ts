import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { getScoutOrigin } from "@posthog/core/scouts/scoutPresentation";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

export interface ScoutConfigUpdate {
  enabled?: boolean;
  emit?: boolean;
  run_interval_minutes?: number;
  run_cron_schedule?: string | null;
  auto_pause_exempt?: boolean;
}

const CONFIG_SETTINGS = [
  "enabled",
  "emit",
  "run_interval_minutes",
  "run_cron_schedule",
  "auto_pause_exempt",
] as const;

function trackConfigChange(
  previousConfig: ScoutConfig | undefined,
  updates: ScoutConfigUpdate,
  success: boolean,
): void {
  if (!previousConfig) return;
  for (const setting of CONFIG_SETTINGS) {
    const newValue = updates[setting];
    if (newValue === undefined) continue;
    track(ANALYTICS_EVENTS.SCOUT_CONFIG_CHANGED, {
      skill_name: previousConfig.skill_name,
      scout_origin: getScoutOrigin(previousConfig),
      setting,
      new_value: newValue,
      // Explicit null, not undefined: `auto_pause_exempt` is optional, and the
      // cloud client normalizes an unknown prior value to null. Undefined would
      // drop the key on serialization and split the two clients' event shape.
      old_value: previousConfig[setting] ?? null,
      success,
    });
  }
}

/**
 * Optimistically patch a scout config (enable/disable, live vs dry-run,
 * cadence) and reconcile with the server response.
 */
export function useScoutConfigMutations() {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const inFlightCount = useRef(0);
  const inFlightConfigIds = useRef(new Set<string>());
  const queuedUpdates = useRef(new Map<string, ScoutConfigUpdate>());

  const updateConfig = useCallback(
    async (configId: string, updates: ScoutConfigUpdate) => {
      if (!client || !projectId) return;
      const queryKey = scoutQueryKeys.configs(projectId);
      const patchLocally = (patch: Partial<ScoutConfig>) =>
        queryClient.setQueryData<ScoutConfig[]>(queryKey, (configs) =>
          configs?.map((config) =>
            config.id === configId ? { ...config, ...patch } : config,
          ),
        );
      // The schedule mode, the run day and the run time all write `run_cron_schedule`, so a
      // second choice can arrive while the first PATCH is still out. Sending both at once lets
      // the server commit them in either order and keep the earlier one, so queue the later
      // update behind the active request instead.
      if (inFlightConfigIds.current.has(configId)) {
        patchLocally(updates);
        queuedUpdates.current.set(configId, {
          ...queuedUpdates.current.get(configId),
          ...updates,
        });
        return;
      }
      let confirmedConfig = queryClient
        .getQueryData<ScoutConfig[]>(queryKey)
        ?.find((config) => config.id === configId);
      patchLocally(updates);
      inFlightConfigIds.current.add(configId);
      inFlightCount.current++;
      let updatesToSend: ScoutConfigUpdate | undefined = updates;
      try {
        while (updatesToSend) {
          const previousConfig = confirmedConfig;
          const updated = await client.updateScoutConfig(
            projectId,
            configId,
            updatesToSend,
          );
          trackConfigChange(previousConfig, updatesToSend, true);
          confirmedConfig = updated;
          updatesToSend = queuedUpdates.current.get(configId);
          queuedUpdates.current.delete(configId);
          // Keep a queued choice on screen while its own request runs.
          patchLocally({ ...updated, ...updatesToSend });
        }
      } catch (error: unknown) {
        // Roll back only this config, so edits to other scouts survive.
        if (confirmedConfig) {
          const rolledBack = confirmedConfig;
          queryClient.setQueryData<ScoutConfig[]>(queryKey, (configs) =>
            configs?.map((config) =>
              config.id === configId ? rolledBack : config,
            ),
          );
        }
        trackConfigChange(confirmedConfig, updatesToSend ?? updates, false);
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update scout config";
        toast.error(message);
      } finally {
        // A queued update belongs to the schedule the failed request was building on, so it is
        // dropped with the rollback rather than sent against a state the server never took.
        queuedUpdates.current.delete(configId);
        inFlightConfigIds.current.delete(configId);
        // Concurrent PATCHes to one scout can settle out of order; once the
        // last one lands, reconcile the cache against the server.
        inFlightCount.current--;
        if (inFlightCount.current === 0) {
          void queryClient.invalidateQueries({ queryKey });
        }
      }
    },
    [client, projectId, queryClient],
  );

  return { updateConfig };
}
