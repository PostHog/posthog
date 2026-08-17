import type { McpServerInstallation } from "@posthog/api-client/posthog-client";
import { mcpKeys } from "@posthog/ui/features/mcp-server-manager/useMcpConnect";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/**
 * The team's MCP Store installations, for the loop form's connector picker.
 * Shares `mcpKeys.installations` with the MCP settings page so connecting a
 * server there shows up here without a refetch.
 */
export function useLoopMcpInstallations(): {
  installations: McpServerInstallation[];
  isLoading: boolean;
} {
  const { data, isLoading } = useAuthenticatedQuery(
    mcpKeys.installations,
    (client) => client.getMcpServerInstallations(),
  );
  return {
    installations: (data as McpServerInstallation[] | undefined) ?? [],
    isLoading,
  };
}
