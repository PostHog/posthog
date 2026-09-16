import {
  type ScoutConfig,
  ScoutRequestError,
} from "@posthog/api-client/posthog-client";
import type { ScoutSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

function runNowErrorMessage(error: unknown): string {
  if (error instanceof ScoutRequestError) {
    if (error.status === 409) return "This agent is already running.";
    if (error.status === 429) {
      return "This project has reached a run, report, or Signals limit. Try again after the limit resets.";
    }
    if (error.status === 403) {
      return "This project does not permit this run. Check agent settings and your access.";
    }
  }
  return "Couldn't start the run.";
}

/** Queue one run of a scout outside its schedule. */
export function useScoutRunNow(config: ScoutConfig, surface: ScoutSurface) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const [isStarting, setIsStarting] = useState(false);

  const runNow = useCallback(async () => {
    if (!client || !projectId || isStarting) return;
    setIsStarting(true);
    try {
      await client.runScoutNow(projectId, config.id);
      track(ANALYTICS_EVENTS.SCOUT_ACTION, {
        action_type: "run_now",
        surface,
        skill_name: config.skill_name,
      });
      toast.success("Run started", {
        description: "It shows up under Runs within a minute.",
      });
      void queryClient.invalidateQueries({
        queryKey: scoutQueryKeys.runs(projectId),
      });
    } catch (error: unknown) {
      toast.error(runNowErrorMessage(error));
    } finally {
      setIsStarting(false);
    }
  }, [
    client,
    projectId,
    isStarting,
    config.id,
    config.skill_name,
    surface,
    queryClient,
  ]);

  return { runNow, isStarting };
}
