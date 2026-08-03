import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/**
 * Set/rotate and clear one revision-scoped env key. Both invalidate the
 * env-keys list for the revision so set/not-set status (tree badges, secret
 * detail) reflects the change.
 */
export function useAgentEnvKeyMutations(idOrSlug: string, revisionId: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: agentApplicationsKeys.envKeys(projectId, idOrSlug, revisionId),
    });

  const setKey = useMutation<void, Error, { key: string; value: string }>({
    mutationFn: ({ key, value }) =>
      client.setAgentEnvKey(idOrSlug, revisionId, key, value),
    onSuccess: () => void invalidate(),
  });
  const clearKey = useMutation<void, Error, { key: string }>({
    mutationFn: ({ key }) => client.clearAgentEnvKey(idOrSlug, revisionId, key),
    onSuccess: () => void invalidate(),
  });

  return { setKey, clearKey };
}
