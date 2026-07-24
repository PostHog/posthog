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
}

const CONFIG_SETTINGS = ["enabled", "emit", "run_interval_minutes"] as const;

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
      old_value: previousConfig[setting],
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

  const updateConfig = useCallback(
    async (configId: string, updates: ScoutConfigUpdate) => {
      if (!client || !projectId) return;
      const queryKey = scoutQueryKeys.configs(projectId);
      const previousConfig = queryClient
        .getQueryData<ScoutConfig[]>(queryKey)
        ?.find((config) => config.id === configId);
      queryClient.setQueryData<ScoutConfig[]>(queryKey, (configs) =>
        configs?.map((config) =>
          config.id === configId ? { ...config, ...updates } : config,
        ),
      );
      inFlightCount.current++;
      try {
        const updated = await client.updateScoutConfig(
          projectId,
          configId,
          updates,
        );
        queryClient.setQueryData<ScoutConfig[]>(queryKey, (configs) =>
          configs?.map((config) => (config.id === configId ? updated : config)),
        );
        trackConfigChange(previousConfig, updates, true);
      } catch (error: unknown) {
        // Roll back only this config so concurrent edits to other scouts
        // survive; same-scout overlap reconciles via the settle invalidation.
        if (previousConfig) {
          queryClient.setQueryData<ScoutConfig[]>(queryKey, (configs) =>
            configs?.map((config) =>
              config.id === configId ? previousConfig : config,
            ),
          );
        }
        trackConfigChange(previousConfig, updates, false);
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update scout config";
        toast.error(message);
      } finally {
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
