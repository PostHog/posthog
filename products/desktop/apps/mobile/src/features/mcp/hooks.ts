import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  authorizeMcpInstallation,
  getMcpInstallationTools,
  getMcpRecommendedServers,
  getMcpServerInstallations,
  installCustomMcpServer,
  installMcpTemplate,
  refreshMcpInstallationTools,
  uninstallMcpServer,
  updateMcpServerInstallation,
  updateMcpToolApproval,
} from "./api";
import type {
  InstallCustomMcpServerOptions,
  InstallMcpTemplateOptions,
  McpApprovalState,
  UpdateMcpServerInstallationOptions,
} from "./types";

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
    queryFn: getMcpRecommendedServers,
    staleTime: 5 * 60 * 1000,
  });
}

export function useMcpInstallations() {
  return useQuery({
    queryKey: mcpKeys.installations(),
    queryFn: getMcpServerInstallations,
    staleTime: 30 * 1000,
  });
}

export function useMcpInstallationTools(installationId: string | null) {
  return useQuery({
    queryKey: mcpKeys.tools(installationId ?? ""),
    queryFn: () => getMcpInstallationTools(installationId as string),
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
      installCustomMcpServer(options),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useInstallMcpTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options: InstallMcpTemplateOptions) =>
      installMcpTemplate(options),
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
    }) => updateMcpServerInstallation(installationId, updates),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useUninstallMcpServer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (installationId: string) => uninstallMcpServer(installationId),
    onSuccess: () => invalidateInstallations(queryClient),
  });
}

export function useAuthorizeMcpInstallation() {
  return useMutation({
    mutationFn: (args: Parameters<typeof authorizeMcpInstallation>[0]) =>
      authorizeMcpInstallation(args),
  });
}

export function useRefreshMcpInstallationTools() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (installationId: string) =>
      refreshMcpInstallationTools(installationId),
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
    }) => updateMcpToolApproval(installationId, toolName, approval_state),
    onSuccess: (_, { installationId }) => {
      queryClient.invalidateQueries({
        queryKey: mcpKeys.tools(installationId),
      });
    },
  });
}

export const MCP_QUERY_KEYS = mcpKeys;
