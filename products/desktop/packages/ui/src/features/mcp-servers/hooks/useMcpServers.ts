import type {
  McpAuthType,
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/posthog-client";
import {
  installCustomWithOAuth,
  installTemplateWithOAuth,
  reauthorizeWithOAuth,
} from "@posthog/core/mcp-servers/installFlow";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
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

// `mcpKeys` + `createOAuthCallback` now live in the shared mcp-server-manager
// module (also used by the agent-applications builder). Re-exported here so
// existing importers (e.g. useMcpInstallationTools) keep their path.
export { mcpKeys };

export function useMcpServers() {
  const trpc = useHostTRPC();
  const trpcClient = useHostTRPCClient();
  const oauth = useMemo(() => createOAuthCallback(trpcClient), [trpcClient]);
  const queryClient = useQueryClient();

  const { data: installations, isLoading: installationsLoading } =
    useAuthenticatedQuery(mcpKeys.installations, (client) =>
      client.getMcpServerInstallations(),
    );

  const { data: servers, isLoading: serversLoading } = useAuthenticatedQuery(
    mcpKeys.servers,
    (client) => client.getMcpServers(),
  );

  const installedTemplateIds = useMemo(
    () =>
      new Set(
        (installations ?? [])
          .map((i) => i.template_id)
          .filter((id): id is string => !!id),
      ),
    [installations],
  );

  const installedUrls = useMemo(
    () =>
      new Set(
        (installations ?? []).map((i) => i.url).filter((u): u is string => !!u),
      ),
    [installations],
  );

  const invalidateInstallations = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: mcpKeys.installations });
  }, [queryClient]);

  const uninstallMutation = useAuthenticatedMutation(
    (client, installationId: string) =>
      client.uninstallMcpServer(installationId),
    {
      onSuccess: () => {
        toast.success("Server uninstalled");
        invalidateInstallations();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to uninstall server");
      },
    },
  );

  const toggleEnabledMutation = useAuthenticatedMutation(
    (client, vars: { id: string; is_enabled: boolean }) =>
      client.updateMcpServerInstallation(vars.id, {
        is_enabled: vars.is_enabled,
      }),
    {
      onSuccess: () => {
        invalidateInstallations();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to update server");
      },
    },
  );

  const toggleEnabled = useCallback(
    (installationId: string, enabled: boolean) => {
      toggleEnabledMutation.mutate({ id: installationId, is_enabled: enabled });
    },
    [toggleEnabledMutation],
  );

  const installTemplateMutation = useAuthenticatedMutation(
    (client, vars: { template_id: string; api_key?: string }) =>
      installTemplateWithOAuth(client, oauth, vars),
    {
      onSuccess: (data) => {
        if (data && "success" in data && data.success) {
          toast.success("Server connected");
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateInstallations();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to connect server");
      },
    },
  );

  const installTemplate = useCallback(
    (template: McpRecommendedServer, opts?: { api_key?: string }) => {
      installTemplateMutation.mutate({
        template_id: template.id,
        api_key: opts?.api_key,
      });
    },
    [installTemplateMutation],
  );

  const installingId = installTemplateMutation.isPending
    ? (installTemplateMutation.variables?.template_id ?? null)
    : null;

  const installCustomMutation = useAuthenticatedMutation(
    (
      client,
      vars: {
        name: string;
        url: string;
        description: string;
        auth_type: McpAuthType;
        api_key?: string;
        client_id?: string;
        client_secret?: string;
      },
    ) => installCustomWithOAuth(client, oauth, vars),
    {
      onSuccess: (data) => {
        if (data && "success" in data && data.success) {
          toast.success("Server added");
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateInstallations();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to add server");
      },
    },
  );

  const reauthorizeMutation = useAuthenticatedMutation(
    (client, installationId: string) =>
      reauthorizeWithOAuth(client, oauth, installationId),
    {
      onSuccess: (data) => {
        if (data && "success" in data && data.success) {
          toast.success("Server reconnected");
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateInstallations();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to reconnect server");
      },
    },
  );

  useSubscription(
    trpc.mcpCallback.onOAuthComplete.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data.status === "success") {
          invalidateInstallations();
        }
      },
    }),
  );

  return {
    installations: installations as McpServerInstallation[] | undefined,
    installationsLoading,
    servers: servers as McpRecommendedServer[] | undefined,
    serversLoading,
    installedTemplateIds,
    installedUrls,
    installingId,
    uninstallMutation,
    toggleEnabled,
    installTemplate,
    installCustom: installCustomMutation.mutate,
    installCustomPending: installCustomMutation.isPending,
    reauthorize: reauthorizeMutation.mutate,
    reauthorizePending: reauthorizeMutation.isPending,
    invalidateInstallations,
  };
}
