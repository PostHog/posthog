import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Delete one custom tool from a draft revision (draft-only). On success the
 * bundle query is invalidated so the removed tool drops out of the explorer.
 */
export function useDeleteRevisionTool(idOrSlug: string, revisionId: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<void, Error, { toolId: string }>({
    mutationFn: ({ toolId }) =>
      client.deleteRevisionTool(idOrSlug, revisionId, toolId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.bundle(projectId, idOrSlug, revisionId),
      });
    },
  });
}
