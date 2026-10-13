import type {
  ScoutSuggestionItem,
  ScoutSuggestionSet,
} from "@posthog/api-client/posthog-client";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

const log = logger.scope("scout-suggestions");

const EMPTY_SET: ScoutSuggestionSet = {
  status: "empty",
  generated_at: null,
  model: "",
  fleet_snapshot: [],
  items: [],
};

/**
 * The pre-computed batch of agents worth adding to this project. A coordinator
 * refreshes it on its own schedule, so this is a plain read: nothing here waits
 * on a model, and a project with no batch reads as an empty list.
 */
export function useScoutSuggestions() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ScoutSuggestionSet>(
    scoutQueryKeys.suggestions(projectId),
    (client) =>
      projectId
        ? client.listScoutSuggestions(projectId)
        : Promise.resolve(EMPTY_SET),
    { enabled: !!projectId, staleTime: 5 * 60_000 },
  );
}

/**
 * Take a suggestion off the list. Acting on one and passing on it both end with
 * it gone, so the card leaves at once and the server catches up. A failed write
 * is not worth a toast: the batch is a recommendation, and the next refresh
 * settles it either way.
 */
export function useDismissScoutSuggestion(): (
  item: ScoutSuggestionItem,
) => void {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  return useCallback(
    (item: ScoutSuggestionItem) => {
      queryClient.setQueryData<ScoutSuggestionSet>(
        scoutQueryKeys.suggestions(projectId),
        (set) =>
          set
            ? { ...set, items: set.items.filter((one) => one.id !== item.id) }
            : set,
      );
      if (!client || !projectId) return;
      void client
        .dismissScoutSuggestion(projectId, item.id)
        .catch((error: unknown) => {
          log.warn("Dismissing a scout suggestion failed", {
            suggestionId: item.id,
            error,
          });
        });
    },
    [client, projectId, queryClient],
  );
}
