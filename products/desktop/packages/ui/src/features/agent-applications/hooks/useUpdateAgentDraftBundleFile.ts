import type { AgentRevision } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Write a single bundle file (agent.md or skills/<id>/SKILL.md) on a draft
 * revision. The server rejects non-draft revisions with 409, so the UI gates
 * on revision state too. Invalidates the bundle (the rendered file body) and
 * the revision (updated_at moves) on success.
 */
export function useUpdateAgentDraftBundleFile(
  idOrSlug: string,
  revisionId: string,
) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<AgentRevision, Error, { path: string; content: string }>({
    mutationFn: ({ path, content }) =>
      client.updateAgentDraftBundleFile(idOrSlug, revisionId, path, content),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.bundle(projectId, idOrSlug, revisionId),
      });
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.revision(
          projectId,
          idOrSlug,
          revisionId,
        ),
      });
    },
  });
}
