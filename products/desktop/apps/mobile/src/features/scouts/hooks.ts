import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { computeScoutRollups } from "@posthog/core/scouts/scoutPresentation";
import type { ScoutRunsWindow } from "@posthog/core/scouts/scoutRunsWindow";
import { fetchScoutRunsWindow } from "@posthog/core/scouts/scoutRunsWindow";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { runsWindowHasRunningRun } from "./lib/scoutRows";

const log = logger.scope("scouts");

/** Switching project drops the whole query cache, so no project id in the key. */
export const scoutKeys = {
  all: ["scouts"] as const,
  configs: () => [...scoutKeys.all, "configs"] as const,
  runs: () => [...scoutKeys.all, "runs"] as const,
};

/**
 * How often the runs window is refetched while a scout is mid-run. Nothing
 * else moves on its own between scheduled dispatches, so polling is gated on
 * there actually being a live run.
 */
const RUNNING_POLL_MS = 30_000;

function useScoutProjectId(): number | null {
  const { projectId, oauthAccessToken } = useAuthStore();
  return projectId && oauthAccessToken ? projectId : null;
}

export function useScoutConfigs() {
  const projectId = useScoutProjectId();
  return useQuery({
    queryKey: scoutKeys.configs(),
    queryFn: () => getPostHogApiClient().listScoutConfigs(projectId as number),
    enabled: projectId !== null,
    staleTime: 30_000,
  });
}

/**
 * Every fleet run in the recent window, assembled in core by walking the
 * backend's 100-row pages. The backend has no per-scout filter, so the screen
 * rolls this up client-side.
 */
export function useScoutRuns() {
  const projectId = useScoutProjectId();
  return useQuery<ScoutRunsWindow>({
    // The queryFn already walks up to 10 pages; a blanket retry restarts
    // the whole walk. Partial windows surface as complete: false instead.
    retry: false,
    queryKey: scoutKeys.runs(),
    queryFn: () =>
      fetchScoutRunsWindow(getPostHogApiClient(), projectId as number),
    enabled: projectId !== null,
    staleTime: 15_000,
    refetchInterval: (query) =>
      runsWindowHasRunningRun(
        query.state.data,
        computeScoutRollups(query.state.data?.runs ?? []),
      )
        ? RUNNING_POLL_MS
        : false,
  });
}

export interface ScoutConfigUpdate {
  /**
   * Flipping this off records a user pause, which the system never overrides;
   * flipping it on resumes the scout from any pause, including a system one.
   */
  enabled?: boolean;
  emit?: boolean;
  run_interval_minutes?: number;
  auto_pause_exempt?: boolean;
}

/**
 * Config writes for the fleet screen. Updates are applied optimistically so a
 * switch or cadence change lands under the finger, and rolled back if the
 * server rejects them.
 */
export function useScoutConfigMutations() {
  const projectId = useScoutProjectId();
  const queryClient = useQueryClient();

  const updateConfig = useMutation({
    mutationFn: ({
      configId,
      updates,
    }: {
      configId: string;
      updates: ScoutConfigUpdate;
    }) =>
      getPostHogApiClient().updateScoutConfig(
        projectId as number,
        configId,
        updates,
      ),
    onMutate: async ({ configId, updates }) => {
      await queryClient.cancelQueries({ queryKey: scoutKeys.configs() });
      const previous = queryClient.getQueryData<ScoutConfig[]>(
        scoutKeys.configs(),
      );
      queryClient.setQueryData<ScoutConfig[]>(scoutKeys.configs(), (old) =>
        old?.map((config) =>
          config.id === configId ? { ...config, ...updates } : config,
        ),
      );
      return { previous };
    },
    onError: (error, { configId }, context) => {
      log.warn("Updating scout config failed; rolled back", {
        configId,
        error: error.message,
      });
      if (context?.previous) {
        queryClient.setQueryData(scoutKeys.configs(), context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: scoutKeys.configs() });
    },
  });

  const runScout = useMutation({
    mutationFn: (configId: string) =>
      getPostHogApiClient().runScoutConfig(projectId as number, configId),
    onSuccess: () => {
      // The run row only appears once the workflow's first turn starts, so
      // refetch the window rather than expecting it in the response.
      queryClient.invalidateQueries({ queryKey: scoutKeys.runs() });
    },
  });

  return { updateConfig, runScout };
}
