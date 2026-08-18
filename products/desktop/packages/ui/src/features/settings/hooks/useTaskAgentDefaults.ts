import {
  type MyTaskRunConfig,
  NO_TASK_RUN_DEFAULTS,
  NO_TASK_RUN_PREFERENCES,
  type TaskRunDefaults,
  type TaskRunPreferences,
} from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

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
  save: (preferences: TaskRunPreferences) => Promise<void>;
  /** Clear the personal preference so the project default applies again. */
  reset: () => Promise<void>;
}

const MY_CONFIG_KEY = "task-agent-my-config";
const TEAM_CONFIG_KEY = "task-agent-team-config";

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
      // The write returns the row and its resolution, so seed the cache rather than
      // refetching what we already hold.
      queryClient.setQueryData([MY_CONFIG_KEY, projectId], next);
    },
  });

  const save = useCallback(
    async (preferences: TaskRunPreferences) => {
      await mutation.mutateAsync(preferences);
    },
    [mutation],
  );

  const reset = useCallback(async () => {
    await mutation.mutateAsync(NO_TASK_RUN_PREFERENCES);
  }, [mutation]);

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
