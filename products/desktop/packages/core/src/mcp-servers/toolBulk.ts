import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/types";

interface ToolApprovalClient {
  updateMcpToolApproval: (
    installationId: string,
    toolName: string,
    approval_state: McpApprovalState,
  ) => Promise<unknown>;
}

/**
 * Fire a PATCH per non-removed tool in parallel. Returns once every request
 * resolves (or rejects — callers should surface the error).
 */
export async function dispatchBulkApproval(
  client: ToolApprovalClient,
  installationId: string,
  tools: McpInstallationTool[],
  approval_state: McpApprovalState,
): Promise<void> {
  await Promise.all(
    tools
      .filter((t) => !t.removed_at)
      .map((t) =>
        client.updateMcpToolApproval(
          installationId,
          t.tool_name,
          approval_state,
        ),
      ),
  );
}
