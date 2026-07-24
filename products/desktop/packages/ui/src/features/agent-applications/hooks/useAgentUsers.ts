import type { AgentUsersListResponse } from "@posthog/shared/agent-platform-types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** The agent's end-users, each with their linked connections (metadata only). */
export function useAgentUsers(idOrSlug: string) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  return useAuthenticatedQuery<AgentUsersListResponse>(
    agentApplicationsKeys.users(projectId, idOrSlug),
    (client) => client.listAgentUsers(idOrSlug),
    // No retry: this only powers an optional filter dropdown (hidden when
    // empty). Until the `/users/` endpoint ships it 404s, and the Sessions tab
    // that calls this auto-polls — retrying would multiply avoidable failing
    // traffic for a feature that degrades gracefully to "no dropdown".
    { enabled: !!projectId && !!idOrSlug, staleTime: 15_000, retry: false },
  );
}

interface DisconnectArgs {
  agentUserId: string;
  provider: string;
}

/**
 * Revoke one of a user's linked connections. The credential is revoked (kept
 * for audit), not hard-deleted; the agent can no longer act as that user on the
 * provider. Refetches the users list on settle so the row reflects the new
 * state, and toasts the outcome.
 */
export function useDisconnectAgentUserConnection(idOrSlug: string) {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();
  const projectId = useAuthStateValue((s) => s.currentProjectId);

  return useMutation<void, Error, DisconnectArgs>({
    mutationFn: ({ agentUserId, provider }) =>
      client.deleteAgentUserConnection(idOrSlug, agentUserId, provider),
    onSuccess: (_data, { provider }) => {
      toast.success("Connection revoked", {
        description: `The agent can no longer act as this user on ${provider}.`,
      });
    },
    onError: (err) => {
      toast.error("Couldn't revoke connection", {
        description: err instanceof Error ? err.message : undefined,
      });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: agentApplicationsKeys.users(projectId, idOrSlug),
      });
    },
  });
}
