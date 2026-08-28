import type { McpGatewayServer } from "@posthog/api-client/posthog-client";
import type { GatewayInstallRequest } from "@posthog/core/mcp-gateway/gatewayAddServer";
import { registerGatewayServerWithOAuth } from "@posthog/core/mcp-gateway/gatewayInstallFlow";
import { discoverGatewayTools } from "@posthog/core/mcp-gateway/gatewayToolDiscovery";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { gatewayKeys } from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import {
  createOAuthCallback,
  mcpKeys,
} from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

interface RegisterGatewayServerResult {
  /** The gateway registration for the just-added server, when resolvable. */
  created: McpGatewayServer | null;
  /** Whether the install also listed the server's tools. */
  discoveredTools: boolean;
  error: string | null;
}

/**
 * Registers a custom server with the gateway (Add-server form submit) and
 * resolves the resulting registry entry so the caller can navigate to it.
 */
export function useRegisterGatewayServer() {
  const trpcClient = useHostTRPCClient();
  const oauth = useMemo(() => createOAuthCallback(trpcClient), [trpcClient]);
  const queryClient = useQueryClient();

  const mutation = useAuthenticatedMutation(
    async (
      client,
      vars: { request: GatewayInstallRequest },
    ): Promise<RegisterGatewayServerResult> => {
      const result = await registerGatewayServerWithOAuth(
        client,
        oauth,
        vars.request,
      );
      if (result?.error) {
        return { created: null, discoveredTools: false, error: result.error };
      }
      // Re-read the registry to find the registration for the new server —
      // the gateway keys servers by (team, url).
      const servers = await client.getMcpGatewayServers();
      queryClient.setQueryData(gatewayKeys.servers, servers);
      const target = normalizeUrl(vars.request.url);
      const created =
        servers.find((server) => normalizeUrl(server.url) === target) ?? null;
      // Registering stores the credential but discovers no tools, and this
      // flow lands the user straight on the server's detail page — list them
      // now so that page isn't empty. A failure here is not a failed install;
      // the detail page retries on mount.
      const discovery = await discoverGatewayTools(
        client,
        { serverId: created?.id, url: vars.request.url },
        { servers },
      ).catch(() => null);
      return { created, discoveredTools: !!discovery?.discovered, error: null };
    },
    {
      onSuccess: (data, vars) => {
        if (data.error) {
          toast.error(data.error);
        } else {
          toast.success(`${vars.request.name} added to the gateway`);
        }
        if (data.discoveredTools && data.created) {
          queryClient.invalidateQueries({
            queryKey: gatewayKeys.serverTools(data.created.id),
          });
          queryClient.invalidateQueries({ queryKey: gatewayKeys.servers });
        }
        queryClient.invalidateQueries({ queryKey: mcpKeys.installations });
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to add server"),
    },
  );

  return {
    register: mutation.mutate,
    registerPending: mutation.isPending,
  };
}
