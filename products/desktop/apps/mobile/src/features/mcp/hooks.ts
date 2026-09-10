import type {
  InstallCustomMcpServerOptions,
  InstallMcpTemplateOptions,
  McpApprovalState,
  UpdateMcpServerInstallationOptions,
} from "@posthog/api-client/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

const mcpKeys = {
  all: ["mcp"] as const,
  marketplace: () => [...mcpKeys.all, "marketplace"] as const,
  installations: () => [...mcpKeys.all, "installations"] as const,
  tools: (installationId: string) =>
    [...mcpKeys.all, "tools", installationId] as const,
};

export function useMcpMarketplace() {
  return useQuery({
    queryKey: mcpKeys.marketplace(),
    queryFn: () => getPostHogApiClient().getMcpServers(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useMcpInstallations() {
  return useQuery({
    queryKey: mcpKeys.installations(),
    queryFn: () => getPostHogApiClient().getMcpServerInstallations(),
    staleTime: 30 * 1000,
  });
}

export function useMcpInstallationTools(installationId: string | null) {
  return useQuery({
    queryKey: mcpKeys.tools(installationId ?? ""),
    queryFn: () =>
      getPostHogApiClient().getMcpInstallationTools(installationId as string),
    enabled: !!installationId,
    staleTime: 30 * 1000,
  });
}

function invalidateInstallations(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  queryClient.invalidateQueries({ queryKey: mcpKeys.installations() });
}

export function useInstallCustomMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options: InstallCustomMcpServerOptions) =>
      getPostHogApiClient().installCustomMcpServer(options),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useInstallMcpTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options: InstallMcpTemplateOptions) =>
      getPostHogApiClient().installMcpTemplate(options),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useUpdateMcpServerInstallation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      installationId,
      updates,
    }: {
      installationId: string;
      updates: UpdateMcpServerInstallationOptions;
    }) =>
      getPostHogApiClient().updateMcpServerInstallation(
        installationId,
        updates,
      ),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useUninstallMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (installationId: string) =>
      getPostHogApiClient().uninstallMcpServer(installationId),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useAuthorizeMcpInstallation() {
  return useMutation({
    mutationFn: (args: {
      installation_id: string;
      install_source?: "posthog" | "posthog-code" | "posthog-mobile";
      posthog_code_callback_url?: string;
    }) => getPostHogApiClient().authorizeMcpInstallation(args),
  });
}

export function useRefreshMcpInstallationTools() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (installationId: string) =>
      getPostHogApiClient().refreshMcpInstallationTools(installationId),
    onSuccess: (_, installationId) => {
      queryClient.invalidateQueries({
        queryKey: mcpKeys.tools(installationId),
      });
      invalidateInstallations(queryClient);
    },
  });
}

export function useUpdateMcpToolApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      installationId,
      toolName,
      approval_state,
    }: {
      installationId: string;
      toolName: string;
      approval_state: McpApprovalState;
    }) =>
      getPostHogApiClient().updateMcpToolApproval(
        installationId,
        toolName,
        approval_state,
      ),
    onSuccess: (_, { installationId }) => {
      queryClient.invalidateQueries({
        queryKey: mcpKeys.tools(installationId),
      });
    },
  });
}

export const MCP_QUERY_KEYS = mcpKeys;
