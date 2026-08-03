import type { AgentRevision } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

interface ImportBody {
  agent_md?: string;
  skills?: { id: string; description?: string; body: string }[];
}

/**
 * Bulk-paste a set of `.md` files into a draft revision — the migration
 * hatch when porting an existing multi-file agent. Merges by skill id (adds
 * new skills, overwrites bodies for existing ids; skills not mentioned are
 * left alone). Draft-only on the server. Invalidates the same caches as the
 * per-file update so the explorer reflects all touched files at once.
 */
export function useImportAgentDraftBundle(
  idOrSlug: string,
  revisionId: string,
) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<AgentRevision, Error, ImportBody>({
    mutationFn: (body) =>
      client.importAgentDraftBundle(idOrSlug, revisionId, body),
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
