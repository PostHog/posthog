import type {
  McpGatewayServer,
  McpGatewayServerUpdate,
  McpRecommendedServer,
} from "@posthog/api-client/posthog-client";
import {
  connectGatewayServer,
  type GatewayConnectCredentials,
} from "@posthog/core/mcp-gateway/gatewayConnect";
import { recommendedCatalogTemplates } from "@posthog/core/mcp-gateway/gatewayServers";
import {
  discoverGatewayTools,
  type GatewayServerMatch,
} from "@posthog/core/mcp-gateway/gatewayToolDiscovery";
import { reauthorizeWithOAuth } from "@posthog/core/mcp-servers/installFlow";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { gatewayKeys } from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import {
  createOAuthCallback,
  mcpKeys,
} from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useMemo } from "react";

/**
 * The team's gateway server registry plus every server-level mutation:
 * connect/disconnect the caller's own credential, the member self-switch, and
 * the admin controls (team enable, personal connections, remove).
 */
export function useGatewayServers() {
  const trpc = useHostTRPC();
  const trpcClient = useHostTRPCClient();
  const oauth = useMemo(() => createOAuthCallback(trpcClient), [trpcClient]);
  const queryClient = useQueryClient();

  const { data: servers, isLoading: serversLoading } = useAuthenticatedQuery(
    gatewayKeys.servers,
    (client) => client.getMcpGatewayServers(),
  );

  // Catalog templates: brand icon domains for gateway rows, plus the
  // connect-only "recommended" cards for templates with no gateway row.
  const { data: templates } = useAuthenticatedQuery(mcpKeys.servers, (client) =>
    client.getMcpServers(),
  );
  const templatesById = useMemo(() => {
    const map = new Map<string, McpRecommendedServer>();
    for (const template of templates ?? []) map.set(template.id, template);
    return map;
  }, [templates]);

  // The registry is sparse — untouched catalog templates have no row.
  const recommendedTemplates = useMemo(
    () => recommendedCatalogTemplates(servers ?? [], templates ?? []),
    [servers, templates],
  );

  const invalidateServers = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: gatewayKeys.servers });
    // Connections are installation rows, so the legacy surfaces change too.
    queryClient.invalidateQueries({ queryKey: mcpKeys.installations });
  }, [queryClient]);

  // Connecting stores a credential but discovers nothing, so a server's first
  // connection has to list the upstream tools itself — otherwise the registry
  // row sits at zero tools until an admin hits the manual refresh.
  const discoverToolsMutation = useAuthenticatedMutation(
    (client, match: GatewayServerMatch) => discoverGatewayTools(client, match),
    {
      onSuccess: (result) => {
        if (!result.discovered || !result.serverId) return;
        queryClient.invalidateQueries({
          queryKey: gatewayKeys.serverTools(result.serverId),
        });
        queryClient.invalidateQueries({ queryKey: gatewayKeys.servers });
      },
      // A failed listing must not read as a failed connect. The detail page
      // still shows its empty state and retries on mount.
      onError: () => {},
    },
  );
  const discoverTools = discoverToolsMutation.mutate;

  // Credentials come from the connect dialog: custom servers have no fixed
  // auth mechanism (each member chooses), api-key templates need the key.
  // Plain OAuth connects pass none and default to the browser round-trip.
  const connectMutation = useAuthenticatedMutation(
    (
      client,
      vars: {
        server: McpGatewayServer;
        credentials?: GatewayConnectCredentials;
      },
    ) => connectGatewayServer(client, oauth, vars.server, vars.credentials),
    {
      onSuccess: (data, vars) => {
        if (data && "success" in data && data.success) {
          toast.success(`Authenticated with ${vars.server.name} as you`);
          discoverTools({ serverId: vars.server.id });
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateServers();
      },
      onError: (error: Error, vars) => {
        toast.error(
          error.message || `Could not connect to ${vars.server.name}`,
        );
        invalidateServers();
      },
    },
  );

  const reconnectMutation = useAuthenticatedMutation(
    (client, vars: { installationId: string; serverName: string }) =>
      reauthorizeWithOAuth(client, oauth, vars.installationId),
    {
      onSuccess: (data, vars) => {
        if (data && "success" in data && data.success) {
          toast.success(`Authenticated with ${vars.serverName} as you`);
          discoverTools({ installationId: vars.installationId });
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateServers();
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to reconnect"),
    },
  );

  const disconnectMutation = useAuthenticatedMutation(
    (
      client,
      vars: {
        installationId: string;
        serverName: string;
        action?: "delete" | "disconnect";
      },
    ) => client.uninstallMcpServer(vars.installationId),
    {
      onSuccess: (_data, vars) => {
        toast.info(
          vars.action === "delete"
            ? `${vars.serverName} deleted for you`
            : `Disconnected from ${vars.serverName}`,
        );
        invalidateServers();
      },
      onError: (error: Error, vars) =>
        toast.error(
          error.message ||
            (vars.action === "delete"
              ? "Failed to delete server"
              : "Failed to disconnect"),
        ),
    },
  );

  // Member self-switch on their own connection ("Disabled for you").
  const toggleYourConnectionMutation = useAuthenticatedMutation(
    (client, vars: { installationId: string; enabled: boolean }) =>
      client.updateMcpServerInstallation(vars.installationId, {
        is_enabled: vars.enabled,
      }),
    {
      onSuccess: invalidateServers,
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update server"),
    },
  );

  // Connect to a catalog template that has no gateway row yet; the backend
  // materializes the row as part of the install. API-key templates carry the
  // member's key from the connect dialog.
  const connectTemplateMutation = useAuthenticatedMutation(
    (
      client,
      vars: {
        template: McpRecommendedServer;
        credentials?: GatewayConnectCredentials;
      },
    ) =>
      connectGatewayServer(
        client,
        oauth,
        {
          template_id: vars.template.id,
          name: vars.template.name,
          url: vars.template.url,
          description: vars.template.description ?? "",
        },
        vars.credentials,
      ),
    {
      onSuccess: (data, vars) => {
        if (data && "success" in data && data.success) {
          toast.success(`Authenticated with ${vars.template.name} as you`);
          discoverTools({
            templateId: vars.template.id,
            url: vars.template.url,
          });
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateServers();
      },
      onError: (error: Error, vars) => {
        toast.error(
          error.message || `Could not connect to ${vars.template.name}`,
        );
        invalidateServers();
      },
    },
  );

  const updateServerMutation = useAuthenticatedMutation(
    (client, vars: { serverId: string; updates: McpGatewayServerUpdate }) =>
      client.updateMcpGatewayServer(vars.serverId, vars.updates),
    {
      onSuccess: invalidateServers,
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update server"),
    },
  );

  // Admin: enable/disable an untouched catalog template, materializing (or
  // updating) its gateway row.
  const setTemplateEnabledMutation = useAuthenticatedMutation(
    (client, vars: { templateId: string; enabled: boolean }) =>
      client.setMcpGatewayTemplateEnabled(vars),
    {
      onSuccess: invalidateServers,
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update server"),
    },
  );

  // One call sets the posture for untouched (and future) catalog servers and
  // bulk-applies the same state to every existing row.
  const setAllEnabledMutation = useAuthenticatedMutation(
    (client, enabled: boolean) =>
      client.setAllMcpGatewayServersEnabled(enabled),
    {
      onSuccess: (_config, enabled) => {
        invalidateServers();
        queryClient.invalidateQueries({ queryKey: gatewayKeys.config });
        if (enabled) {
          toast.success("Every server is enabled for the team");
        } else {
          toast.info("All servers disabled — new catalog servers stay off too");
        }
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update servers"),
    },
  );

  const removeServerMutation = useAuthenticatedMutation(
    (client, vars: { serverId: string; serverName: string }) =>
      client.deleteMcpGatewayServer(vars.serverId),
    {
      onSuccess: (_data, vars) => {
        toast.info(`${vars.serverName} deleted for everyone`);
        invalidateServers();
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to remove server"),
    },
  );

  useSubscription(
    trpc.mcpCallback.onOAuthComplete.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data.status === "success") invalidateServers();
      },
    }),
  );

  return {
    servers: servers ?? [],
    serversLoading,
    templatesById,
    recommendedTemplates,
    invalidateServers,
    connect: connectMutation.mutate,
    connectingServerId: connectMutation.isPending
      ? (connectMutation.variables?.server.id ?? null)
      : null,
    connectTemplate: connectTemplateMutation.mutate,
    connectingTemplateId: connectTemplateMutation.isPending
      ? (connectTemplateMutation.variables?.template.id ?? null)
      : null,
    reconnect: reconnectMutation.mutate,
    reconnectPending: reconnectMutation.isPending,
    disconnect: disconnectMutation.mutate,
    disconnectPending: disconnectMutation.isPending,
    toggleYourConnection: toggleYourConnectionMutation.mutate,
    updateServer: updateServerMutation.mutate,
    setTemplateEnabled: setTemplateEnabledMutation.mutate,
    setAllEnabled: setAllEnabledMutation.mutate,
    setAllEnabledPending: setAllEnabledMutation.isPending,
    removeServer: removeServerMutation.mutate,
    removeServerPending: removeServerMutation.isPending,
  };
}
