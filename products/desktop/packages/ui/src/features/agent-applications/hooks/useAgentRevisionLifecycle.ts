import type { AgentRevision } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

type LifecycleAction = "freeze" | "promote" | "archive";

/**
 * Run a revision lifecycle transition (freeze / promote / archive). Promote
 * rewrites the application's live_revision and demotes the old live, so on
 * success we invalidate the application detail, the revisions list, and the
 * per-revision + bundle caches.
 */
export function useAgentRevisionLifecycle(idOrSlug: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<
    AgentRevision,
    Error,
    { revisionId: string; action: LifecycleAction }
  >({
    mutationFn: ({ revisionId, action }) =>
      client.transitionAgentRevision(idOrSlug, revisionId, action),
    onSuccess: () => {
      for (const key of [
        agentApplicationsKeys.detail(projectId, idOrSlug),
        agentApplicationsKeys.revisions(projectId, idOrSlug),
        ["agent-applications", "revision", projectId, idOrSlug],
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
