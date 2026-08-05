import { LOCAL_MCP_IMPORT_SERVICE } from "@posthog/core/local-mcp/identifiers";
import type { LocalMcpImportService } from "@posthog/core/local-mcp/localMcpImport";
import { useServiceOptional } from "@posthog/di/react";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";

// Stable identity so consumers' memo deps don't churn while data is absent.
const NO_SERVERS: LocalMcpServerDescriptor[] = [];

export interface LocalMcpServersResult {
  servers: LocalMcpServerDescriptor[];
  /** False on hosts without a local workspace (web/mobile). */
  available: boolean;
}

/** The user's local (~/.claude.json) MCP servers, user scope only. */
export function useLocalMcpServers(enabled: boolean): LocalMcpServersResult {
  const service = useServiceOptional<LocalMcpImportService>(
    LOCAL_MCP_IMPORT_SERVICE,
  );
  const queryEnabled = enabled && !!service;

  const query = useQuery({
    queryKey: ["local-mcp-servers"],
    queryFn: () => (service ? service.listServers() : NO_SERVERS),
    enabled: queryEnabled,
    staleTime: 30_000,
  });

  return {
    servers: queryEnabled ? (query.data ?? NO_SERVERS) : NO_SERVERS,
    available: !!service,
  };
}
