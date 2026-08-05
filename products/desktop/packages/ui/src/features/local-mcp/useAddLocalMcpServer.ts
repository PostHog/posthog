import { LOCAL_MCP_IMPORT_SERVICE } from "@posthog/core/local-mcp/identifiers";
import type { LocalMcpImportService } from "@posthog/core/local-mcp/localMcpImport";
import { useServiceOptional } from "@posthog/di/react";
import {
  useMutation,
  type UseMutationResult,
  useQueryClient,
} from "@tanstack/react-query";

export interface AddLocalMcpServerInput {
  name: string;
  url: string;
}

/**
 * Adds or replaces a user-scoped streamable-HTTP server in the local agent
 * config (~/.claude.json). Desktop only: the mutation rejects on hosts
 * without a local workspace.
 */
export function useAddLocalMcpServer(): UseMutationResult<
  void,
  Error,
  AddLocalMcpServerInput
> {
  const service = useServiceOptional<LocalMcpImportService>(
    LOCAL_MCP_IMPORT_SERVICE,
  );
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: AddLocalMcpServerInput) => {
      if (!service) {
        throw new Error("Local MCP servers require the desktop app.");
      }
      await service.addUserHttpServer(input);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["local-mcp-servers"] }),
        queryClient.invalidateQueries({
          queryKey: ["local-mcp-cloud-availability"],
        }),
      ]);
    },
  });
}
