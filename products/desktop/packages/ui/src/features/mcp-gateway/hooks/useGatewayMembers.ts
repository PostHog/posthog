import type {
  McpGatewayMemberSummary,
  McpGatewayServer,
} from "@posthog/api-client/posthog-client";
import { gatewayKeys } from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";

function setIdEnabled<T extends string | number>(
  ids: readonly T[],
  id: T,
  enabled: boolean,
): T[] {
  if (enabled) return ids.filter((entry) => entry !== id);
  return ids.includes(id) ? [...ids] : [...ids, id];
}

/** Admin overview of members plus the per-member server kill switch. */
export function useGatewayMembers(options: { enabled: boolean }) {
  const queryClient = useQueryClient();

  const { data: members, isLoading } = useAuthenticatedQuery(
    gatewayKeys.members,
    (client) => client.getMcpGatewayMembers(),
    { enabled: options.enabled },
  );

  const setAccessMutation = useAuthenticatedMutation(
    (
      client,
      vars: {
        userId: number;
        serverId: string;
        enabled: boolean;
        /** Toast copy, e.g. "Jonah can now use Forge". */
        successMessage?: string;
      },
    ) =>
      client.setMcpGatewayMemberAccess(vars.userId, {
        gateway_server_id: vars.serverId,
        enabled: vars.enabled,
      }),
    {
      onSuccess: (_data, vars) => {
        // The endpoint has no response body, so apply the known change to
        // both access views. An immediate refetch can briefly return the old
        // access snapshot and make a successful revoke appear to do nothing.
        queryClient.setQueryData<McpGatewayMemberSummary[]>(
          gatewayKeys.members,
          (current) =>
            current?.map((member) =>
              member.user.id === vars.userId
                ? {
                    ...member,
                    revoked_server_ids: setIdEnabled(
                      member.revoked_server_ids,
                      vars.serverId,
                      vars.enabled,
                    ),
                  }
                : member,
            ),
        );
        queryClient.setQueryData<McpGatewayServer[]>(
          gatewayKeys.servers,
          (current) =>
            current?.map((server) =>
              server.id === vars.serverId
                ? {
                    ...server,
                    revoked_user_ids: setIdEnabled(
                      server.revoked_user_ids,
                      vars.userId,
                      vars.enabled,
                    ),
                  }
                : server,
            ),
        );
        if (vars.successMessage) {
          if (vars.enabled) toast.success(vars.successMessage);
          else toast.info(vars.successMessage);
        }
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update member access"),
    },
  );

  return {
    members: members ?? [],
    membersLoading: isLoading,
    setMemberAccess: setAccessMutation.mutate,
  };
}
