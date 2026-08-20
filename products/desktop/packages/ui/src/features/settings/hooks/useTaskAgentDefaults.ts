import {
  type MyTaskRunConfig,
  NO_TASK_RUN_DEFAULTS,
  NO_TASK_RUN_PREFERENCES,
  type TaskRunDefaults,
  type TaskRunPreferences,
} from "@posthog/api-client/posthog-client";
import { preferredRunAdapter } from "@posthog/core/task-detail/previewConfig";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { taskRunDefaultsQueryKey } from "@posthog/ui/features/task-detail/hooks/useTaskRunDefaults";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

export interface TaskAgentDefaultsResult {
  /** The project-wide default, which only project admins can change. */
  teamPreferences: TaskRunPreferences;
  /** What this user has stored for the project; all-null means "inherit". */
  myPreferences: TaskRunPreferences;
  /** What a run without an explicit pick actually launches on. */
  resolved: TaskRunDefaults;
  isLoading: boolean;
  isSaving: boolean;
  /** Persist a personal preference; an all-null triple clears it. */
  save: (preferences: TaskRunPreferences) => void;
  /** Clear the personal preference so the project default applies again. */
  reset: () => void;
}

const MY_CONFIG_KEY = "task-agent-my-config";
const TEAM_CONFIG_KEY = "task-agent-team-config";

/**
 * Picking a model and then its effort is two interactions moments apart, and writing on
 * each one costs two round trips and two re-renders — which is what the settings page
 * flickers on. Long enough to coalesce a pair, short enough that nobody waits on it.
 */
const SAVE_DEBOUNCE_MS = 600;

/**
 * The project and personal task-agent defaults for the current project.
 *
 * Reads both levels because the settings page names what the project sets as well as
 * what this person overrode it with — seeing only the resolved answer leaves "why is
 * it this model" unanswerable. Writes are personal-only: the project default is
 * admin-gated server-side, so offering a control for it here would just 403.
 */
export function useTaskAgentDefaults(): TaskAgentDefaultsResult {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const enabled = projectId != null;

  const myConfig = useAuthenticatedQuery(
    [MY_CONFIG_KEY, projectId],
    async (c) => await c.getMyTaskRunConfig(Number(projectId)),
    { enabled, retry: false },
  );
  const teamConfig = useAuthenticatedQuery(
    [TEAM_CONFIG_KEY, projectId],
    async (c) => await c.getTeamTaskRunPreferences(Number(projectId)),
    { enabled, retry: false },
  );

  const mutation = useMutation({
    mutationFn: async (preferences: TaskRunPreferences) => {
      if (!client || projectId == null) {
        throw new Error("Not authenticated");
      }
      return await client.updateMyTaskRunPreferences(
        Number(projectId),
        preferences,
      );
    },
    onSuccess: (next: MyTaskRunConfig) => {
      // The write returns the row and its resolution, so seed both caches from it — the
      // page and the composer show the new value without waiting on a round trip.
      queryClient.setQueryData([MY_CONFIG_KEY, projectId], next);
      queryClient.setQueryData(
        taskRunDefaultsQueryKey(projectId),
        next.resolved,
      );
      // Then invalidate rather than trust the seed. The composer holds this for the whole
      // stale window, so anything the seed misses — a key that didn't match, an observer
      // mounted elsewhere — would leave the task UI opening on the replaced model until
      // it expired. Invalidating makes the next read go to the server regardless.
      void queryClient.invalidateQueries({
        queryKey: taskRunDefaultsQueryKey(projectId),
      });
      // A stored last-used pick outranks the preference in the composer, so without this
      // the new default would be shadowed on any device that has ever picked a model —
      // the setting would look ignored. Choosing a default here is the more deliberate
      // act of the two, so it clears the stale pick. Same reset the v1 migration does.
      const settings = useSettingsStore.getState();
      settings.setLastUsedModel(null);
      settings.setLastUsedReasoningEffort(null);
      // The harness has to move with it. The composer opens on whichever adapter it last
      // used and ignores a default belonging to a different one, so a Claude default set
      // from a composer left on Codex would be skipped outright — clearing the model
      // alone doesn't help, because the two never meet.
      const adapter = preferredRunAdapter(next.resolved);
      if (adapter) {
        settings.setLastUsedAdapter(adapter);
      }
    },
  });

  const pending = useRef<TaskRunPreferences | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mutate = mutation.mutate;

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const next = pending.current;
    pending.current = null;
    if (next) mutate(next);
  }, [mutate]);

  const save = useCallback(
    (preferences: TaskRunPreferences) => {
      pending.current = preferences;
      // Show the pick straight away; the debounced write only decides when it lands.
      queryClient.setQueryData(
        [MY_CONFIG_KEY, projectId],
        (prev: MyTaskRunConfig | undefined) =>
          prev ? { ...prev, preferences } : prev,
      );
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(flush, SAVE_DEBOUNCE_MS);
    },
    [flush, queryClient, projectId],
  );

  const reset = useCallback(() => {
    pending.current = NO_TASK_RUN_PREFERENCES;
    flush();
  }, [flush]);

  // A pick made and then navigated away from within the debounce window still has to
  // land — the alternative is silently dropping the change the user just made.
  useEffect(() => flush, [flush]);

  return {
    teamPreferences: teamConfig.data ?? NO_TASK_RUN_PREFERENCES,
    myPreferences: myConfig.data?.preferences ?? NO_TASK_RUN_PREFERENCES,
    resolved: myConfig.data?.resolved ?? NO_TASK_RUN_DEFAULTS,
    isLoading: enabled && (myConfig.isLoading || teamConfig.isLoading),
    isSaving: mutation.isPending,
    save,
    reset,
  };
}
