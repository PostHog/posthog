import type {
  ScoutConfig,
  ScoutSuggestionItem,
  ScoutSuggestionSet,
} from "@posthog/api-client/posthog-client";
import { ScoutRequestError } from "@posthog/api-client/posthog-client";
import { suggestionToCreateInput } from "@posthog/core/scouts/scoutSuggestions";
import type { ScoutSuggestionSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * When a scan has not landed by here, stop polling. The scan may run for half an
 * hour and wait as long again for a worker, so this sits past both; the next
 * visit reads whatever it produced.
 */
const SCAN_TIMEOUT_MS = 60 * 60_000;

export interface ScoutSuggestionActions {
  /** Picks hidden since the last read: dismissed, or turned into a scout. */
  hiddenIds: string[];
  /** Picks with a request in flight, so their card shows the work. */
  busyIds: string[];
  /** True from the refresh press until the new batch lands or the wait expires. */
  isScanning: boolean;
  dismiss: (item: ScoutSuggestionItem) => Promise<void>;
  /** Turn a canonical pick on, or create a custom one from its draft. */
  activate: (item: ScoutSuggestionItem) => Promise<void>;
  /** Pay for a new scan now instead of waiting for the scheduled one. */
  refresh: () => Promise<void>;
}

/**
 * Acting on one pre-computed suggestion: dismiss it, turn it into a running
 * scout, or ask for a new batch.
 *
 * Every path hides the card the moment it is pressed and puts it back when the
 * request fails, because a pick that silently stays on screen reads as a press
 * that did nothing.
 */
export function useScoutSuggestionActions({
  surface,
  suggestionSet,
}: {
  surface: ScoutSuggestionSurface;
  /** The batch on screen, so a landed scan can end the wait. */
  suggestionSet: ScoutSuggestionSet | null | undefined;
}): ScoutSuggestionActions {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const [busyIds, setBusyIds] = useState<string[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const scanBaseline = useRef<{
    generatedAt: string | null;
    status: string | null;
    startedAt: number;
  } | null>(null);

  const startAction = useCallback((id: string) => {
    setHiddenIds((ids) => (ids.includes(id) ? ids : [...ids, id]));
    setBusyIds((ids) => [...ids, id]);
  }, []);
  const restore = useCallback((id: string) => {
    setHiddenIds((ids) => ids.filter((candidate) => candidate !== id));
  }, []);
  const settle = useCallback((id: string) => {
    setBusyIds((ids) => ids.filter((candidate) => candidate !== id));
  }, []);

  const dismiss = useCallback(
    async (item: ScoutSuggestionItem) => {
      if (!client || !projectId) return;
      startAction(item.id);
      try {
        await client.dismissScoutSuggestion(projectId, item.id);
        track(ANALYTICS_EVENTS.SCOUT_SUGGESTION_DISMISSED, {
          suggestion_kind: item.kind,
          skill_name: item.skill_name,
          surface,
        });
      } catch (error) {
        // A dismissal has no undo, so a failed one comes back rather than
        // disappearing until the next read says it was never hidden.
        restore(item.id);
        toast.error(errorMessage(error, "Couldn't dismiss that suggestion"));
      } finally {
        settle(item.id);
      }
    },
    [client, projectId, surface, startAction, restore, settle],
  );

  const activate = useCallback(
    async (item: ScoutSuggestionItem) => {
      if (!client || !projectId) return;
      track(ANALYTICS_EVENTS.SCOUT_SUGGESTION_CLICKED, {
        suggestion_kind: item.kind,
        skill_name: item.skill_name,
        click_target: item.kind === "canonical" ? "turn_on" : "create",
        surface,
      });
      startAction(item.id);
      try {
        if (item.kind === "canonical") {
          // The scout already exists on the project, so turning it on is the
          // roster's own update. The rest of its settings — cadence, dry-run
          // posture, destinations — stay as the project has them.
          const config = queryClient
            .getQueryData<ScoutConfig[]>(scoutQueryKeys.configs(projectId))
            ?.find((candidate) => candidate.skill_name === item.skill_name);
          if (!config) {
            // The fleet is materialized when the section opens, so a missing row
            // means that sync has not landed rather than a scout that is absent.
            throw new Error(
              "This scout is still being set up on your project. Try again in a moment.",
            );
          }
          await client.updateScoutConfig(projectId, config.id, {
            enabled: true,
          });
        } else {
          await client.createScout(projectId, suggestionToCreateInput(item));
        }
        track(ANALYTICS_EVENTS.SCOUT_SUGGESTION_CREATED, {
          suggestion_kind: item.kind,
          skill_name: item.skill_name,
          via: "api",
          surface,
        });
        toast.success(`${item.title} is now running.`);
        void queryClient.invalidateQueries({
          queryKey: scoutQueryKeys.configs(projectId),
        });
        void queryClient.invalidateQueries({
          queryKey: scoutQueryKeys.suggestions(projectId),
        });
      } catch (error) {
        restore(item.id);
        toast.error(errorMessage(error, "Couldn't set that scout up"));
      } finally {
        settle(item.id);
      }
    },
    [client, projectId, queryClient, surface, startAction, restore, settle],
  );

  const refresh = useCallback(async () => {
    if (!client || !projectId || isScanning) return;
    const startScan = () => {
      scanBaseline.current = {
        generatedAt: suggestionSet?.generated_at ?? null,
        status: suggestionSet?.status ?? null,
        startedAt: Date.now(),
      };
      setIsScanning(true);
    };
    try {
      await client.refreshScoutSuggestions(projectId);
      track(ANALYTICS_EVENTS.SCOUT_SUGGESTIONS_REFRESHED, {
        outcome: "accepted",
      });
      startScan();
    } catch (error) {
      const status = error instanceof ScoutRequestError ? error.status : null;
      if (status === 409) {
        // A scan is already running, which is the state the wait describes anyway.
        track(ANALYTICS_EVENTS.SCOUT_SUGGESTIONS_REFRESHED, {
          outcome: "running",
        });
        startScan();
        return;
      }
      track(ANALYTICS_EVENTS.SCOUT_SUGGESTIONS_REFRESHED, {
        outcome: status === 429 ? "capped" : "failed",
      });
      // The endpoint refuses for ordinary reasons — the daily cap, the
      // organization's AI setting, a quota — so its own message is the useful one.
      toast.error(errorMessage(error, "Couldn't start a new scan"));
    }
  }, [client, projectId, isScanning, suggestionSet]);

  useEffect(() => {
    const baseline = scanBaseline.current;
    if (!isScanning || !baseline) return;
    // A scan that produced nothing still lands as a `failed` batch, so any
    // conclusion ends the wait. A batch that was already failed is the old
    // failure, not this scan settling.
    const settled =
      (suggestionSet?.generated_at ?? null) !== baseline.generatedAt ||
      (suggestionSet?.status === "failed" && baseline.status !== "failed");
    if (settled || Date.now() - baseline.startedAt >= SCAN_TIMEOUT_MS) {
      setIsScanning(false);
      scanBaseline.current = null;
    }
  }, [isScanning, suggestionSet]);

  return { hiddenIds, busyIds, isScanning, dismiss, activate, refresh };
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ScoutRequestError) return error.detail ?? fallback;
  return error instanceof Error ? error.message : fallback;
}
