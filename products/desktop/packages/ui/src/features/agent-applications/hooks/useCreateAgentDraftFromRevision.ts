import type { AgentRevision } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Fork an existing revision into a fresh editable draft (one round trip via
 * `…/revisions/new_draft/`). The standard exit for "I want to keep iterating
 * on this ready / live / archived revision" — the source bundle is immutable,
 * so we branch off a copy. Returns the new revision so the caller can select
 * it in the picker immediately.
 *
 * The body wants the application's UUID, not its slug, so callers pass
 * `application.id` explicitly (the URL slug used elsewhere wouldn't work).
 */
export function useCreateAgentDraftFromRevision(
  idOrSlug: string,
  applicationId: string | undefined,
) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<AgentRevision, Error, { sourceRevisionId: string }>({
    mutationFn: ({ sourceRevisionId }) => {
      if (!applicationId) {
        throw new Error("Application not loaded yet");
      }
      return client.createAgentDraftRevisionFrom(
        applicationId,
        sourceRevisionId,
      );
    },
    onSuccess: () => {
      // Refresh the revisions list so the new draft shows up in the picker.
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.revisions(projectId, idOrSlug),
      });
    },
  });
}
