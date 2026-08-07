import type {
  WriteToolRequest,
  WriteToolResult,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

interface SaveToolArgs {
  toolId: string;
  body: WriteToolRequest;
}

/**
 * Author/compile one custom tool on a draft revision (PUT). A compile failure is
 * a typed `{ ok: false }` result (HTTP 422), not a throw, so the caller inspects
 * the returned {@link WriteToolResult} to render inline diagnostics. Only a
 * successful compile persists, so the bundle query is invalidated only then — the
 * explorer/editor then reflects the saved source.
 */
export function useSaveRevisionTool(idOrSlug: string, revisionId: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useMutation<WriteToolResult, Error, SaveToolArgs>({
    mutationFn: ({ toolId, body }) =>
      client.putRevisionTool(idOrSlug, revisionId, toolId, body),
    onSuccess: (result) => {
      if (result.ok) {
        void queryClient.invalidateQueries({
          queryKey: agentApplicationsKeys.bundle(
            projectId,
            idOrSlug,
            revisionId,
          ),
        });
      }
    },
  });
}
